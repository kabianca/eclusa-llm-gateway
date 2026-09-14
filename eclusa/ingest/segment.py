"""From paragraphs to citable units.

A citation in this project is a document id plus a locator — ``art. 24, § 3º, VI,
g, 2`` — and the contract refuses an answer whose citations do not resolve. So
every paragraph the extractor delivers has to know where it sits: which article,
which paragraph of it, which inciso, alínea and item. That is what a segment is:
one paragraph, its kind, its locator, and the chapter/section headings in force.

Brazilian normative drafting nests devices in a fixed order — artigo > parágrafo
(§ or parágrafo único) > inciso (roman numeral) > alínea (letter, two letters
past z) > item (number) — and each device resets the levels below it. The walk
below is that grammar. Two things outside the grammar are handled explicitly:
quoted blocks in amending acts, whose inner devices belong to the *quoting*
article and are never parsed as the act's own (a "§ 1º" inside a quotation is
not § 1º of the amending act); and the document's frame — preamble before the
first article, revocation notice, closing matter after the last one — which
carries no locator and is never cited as law.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from eclusa.ingest.extract import (
    CHAPTER,
    OPENS_QUOTE,
    REVOCATION,
    SECTION,
    QuoteState,
    article_labels,
    frame_start,
    is_heading,
)

PARAGRAPH = re.compile(r"^§ (?P<n>\d+)(?:º)?(?P<suffix>-[A-Z])?")
PARAGRAPH_UNICO = re.compile(r"^Parágrafo único")
INCISO = re.compile(r"^(?P<n>[IVXL]+) - ")
ALINEA = re.compile(r"^(?P<n>[a-z]{1,2})\) ")
ITEM = re.compile(r"^(?P<n>\d+)\. ")
NOTE = re.compile(r"^\(")  # "(Redação dada pela ...)", "(NR)", "(Revogado ...)"
ANNEX = re.compile(r"^(NOTA|VOTO|EXPOSIÇÃO DE MOTIVOS)\b")  # a justification attached after the act

Kind = Literal[
    "preamble",
    "revocation_notice",
    "heading",
    "caput",
    "paragraph",
    "inciso",
    "alinea",
    "item",
    "continuation",
    "quoted",
    "note",
    "closing",
    "annex",
]


@dataclass(frozen=True)
class Locator:
    article: str
    paragraph: str | None = None  # "3" for § 3º, "único" for parágrafo único
    inciso: str | None = None
    alinea: str | None = None
    item: str | None = None

    def cite(self, kind: Kind | None = None) -> str:
        parts = [f"art. {_ordinal(self.article)}"]
        if self.paragraph == "único":
            parts.append("parágrafo único")
        elif self.paragraph is not None:
            parts.append(f"§ {_ordinal(self.paragraph)}")
        elif kind == "caput":
            parts.append("caput")
        parts.extend(p for p in (self.inciso, self.alinea, self.item) if p is not None)
        return ", ".join(parts)


@dataclass(frozen=True)
class Segment:
    doc_id: str
    index: int  # position in the document's paragraph list
    kind: Kind
    locator: Locator | None
    heading_path: tuple[str, ...]
    text: str

    @property
    def citation(self) -> str | None:
        return None if self.locator is None else self.locator.cite(self.kind)


def _ordinal(label: str) -> str:
    """Articles and paragraphs 1 to 9 take the ordinal marker: art. 1º, art. 9º-A, art. 10."""
    number, _, suffix = label.partition("-")
    marker = "º" if number.isdigit() and int(number) < 10 else ""
    return f"{number}{marker}{'-' + suffix if suffix else ''}"


def segment(doc_id: str, paragraphs: list[str]) -> list[Segment]:
    """One segment per paragraph, in order. Every paragraph gets exactly one."""
    labels = article_labels(paragraphs)
    first = next((i for i, label in enumerate(labels) if label), None)
    if first is None:
        raise ValueError(f"{doc_id}: no article, nothing to locate")
    last = max(i for i, label in enumerate(labels) if label)
    frame_from = frame_start(paragraphs, last)

    segments: list[Segment] = []
    headings: list[str] = []
    locator: Locator | None = None
    quotes = QuoteState()
    after_section = False
    in_annex = False
    for i, text in enumerate(paragraphs):
        kind: Kind
        if i >= frame_from:
            in_annex = in_annex or ANNEX.match(text) is not None
            kind, locator_here = ("annex" if in_annex else "closing"), None
        elif REVOCATION.match(text):
            kind, locator_here = "revocation_notice", None
        elif i < first:
            kind = "heading" if is_heading(text) else "preamble"
            locator_here = None
            if kind == "heading" and _structural(headings, text):
                # Before the first article, the act's title and "RESOLVE:" are headings too;
                # only CAPÍTULO/Seção labels and their titles belong to the heading path.
                _push_heading(headings, text)
        elif quotes.inside or OPENS_QUOTE.match(text):
            kind, locator_here = "quoted", locator
        elif labels[i]:
            locator = Locator(article=labels[i])
            kind, locator_here = "caput", locator
        elif is_heading(text) or after_section:
            kind, locator_here = "heading", None
            _push_heading(headings, text)
        elif NOTE.match(text) and segments and segments[-1].kind == "heading":
            # "(Seção com redação dada pela ...)" annotates the heading, not the device before it.
            kind, locator_here = "note", None
        else:
            kind, locator = _device(text, locator)
            locator_here = locator
        quotes.update(text)
        after_section = SECTION.match(text) is not None
        segments.append(Segment(doc_id, i, kind, locator_here, tuple(headings), text))
    return segments


def _device(text: str, current: Locator | None) -> tuple[Kind, Locator | None]:
    """Classify a body paragraph under the current article and move the locator."""
    assert current is not None, "a device before the first article"
    if m := PARAGRAPH.match(text):
        return "paragraph", Locator(current.article, paragraph=m["n"] + (m["suffix"] or ""))
    if PARAGRAPH_UNICO.match(text):
        return "paragraph", Locator(current.article, paragraph="único")
    if m := INCISO.match(text):
        return "inciso", Locator(current.article, current.paragraph, inciso=m["n"])
    if m := ALINEA.match(text):
        return "alinea", Locator(current.article, current.paragraph, current.inciso, alinea=m["n"])
    if m := ITEM.match(text):
        return "item", Locator(
            current.article, current.paragraph, current.inciso, current.alinea, item=m["n"]
        )
    if NOTE.match(text):
        return "note", current
    return "continuation", current


def _structural(path: list[str], text: str) -> bool:
    """A CAPÍTULO/Seção label, or the title completing a label just pushed."""
    if CHAPTER.match(text) or SECTION.match(text):
        return True
    return bool(path) and _bare_label(path[-1])


def _push_heading(path: list[str], text: str) -> None:
    """Keep the chapter/section path current.

    A CAPÍTULO label opens the path; a Seção/Subseção label opens a level under it;
    the title that follows a label completes it ("CAPÍTULO V — DOS PROCEDIMENTOS...").
    A title with no label — the 2009 layout has section titles without "Seção N" —
    replaces the previous unlabelled title at its level rather than piling up.
    """
    if CHAPTER.match(text):
        path[:] = [text]
    elif SECTION.match(text):
        depth = 2 if text.startswith("Subseção") else 1
        del path[depth:]
        while len(path) < depth:
            path.append("")
        path.append(text)
    elif path and _bare_label(path[-1]):
        path[-1] = f"{path[-1]} — {text}"
    elif path and not _labelled(path[-1]):
        path[-1] = text
    else:
        path.append(text)


def _labelled(entry: str) -> bool:
    label = entry.split(" — ")[0]
    return CHAPTER.match(label) is not None or SECTION.match(label) is not None


def _bare_label(entry: str) -> bool:
    return _labelled(entry) and " — " not in entry
