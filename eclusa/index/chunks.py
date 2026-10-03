"""From segments to the passages that get embedded.

A citation must resolve to a passage that was actually retrieved, so a chunk is
first of all a set of segments — it knows which paragraphs it contains and what
they are called. What is embedded is those paragraphs with a short header naming
the act, its version status, the headings in force and the citation of the unit,
because "I - dos clientes;" means nothing on its own and "Circular nº 3.978,
art. 2º, parágrafo único" is half of what a question about it says.

The unit is the caput or the § with everything nested under it (incisos,
alíneas, items, notes). A unit longer than the token budget is split greedily,
and every piece repeats the head so that no piece is context-free.

Three kinds of chunk, because the corpus holds three kinds of passage:

- ``unit`` — the law: a caput or § of the act, with what nests under it.
- ``notice`` — a revoked act's revocation notice, on its own, because it is the
  passage an answer about a revoked act has to cite.
- ``amendment`` — an amending act's own article *together with the text it
  quotes*: "Art. 1º A Circular nº 3.978 … passa a vigorar com as seguintes
  alterações: «Art. 23-A …»". For a while the quoted blocks were dropped, on
  the grounds that they duplicate consolidated text which already carries its
  provenance marker and would compete with it in retrieval. The competition is
  real, but dropping them threw away ten per cent of the corpus and, with it,
  every question of the form "what did act X change?" — which the corpus does
  answer, verbatim, in exactly those blocks. So they are embedded, joined to
  the article that quotes them so they can never pass for the law itself, and
  the retrieval layer ranks them below text in force unless the question names
  the amending act. The header says what they are.

The frame — preamble, headings, signatures, an attached technical note — is
never embedded: it is not citable as law.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from eclusa.corpus.manifest import Document, Manifest, Status, VersionKind
from eclusa.ingest.segment import Segment

TOKEN_BUDGET = 400  # of the model's 512, leaving room for the header and the "passage: " prefix
HEAD_KINDS = ("caput", "paragraph")
BODY_KINDS = ("inciso", "alinea", "item", "note", "continuation")
POLICY = "units-v2"  # bump when the chunking rules change: the index is derived from them
QUOTED = "quoted"  # a segment of the text an amending act transcribes


@dataclass(frozen=True)
class Chunk:
    chunk_id: str  # "<doc_id>#<index of the unit's head>[.<piece>]" — deterministic
    doc_id: str
    kind: Literal["unit", "notice", "amendment"]
    citation: str | None  # of the unit's head; None for the revocation notice
    segment_indexes: tuple[int, ...]
    text: str  # header + paragraphs: exactly what is embedded


def is_embeddable(s: Segment) -> bool:
    """What retrieval can return: devices with a locator, quoted text, the revocation notice."""
    return s.kind == "revocation_notice" or (
        s.kind in HEAD_KINDS + BODY_KINDS + (QUOTED,) and s.locator is not None
    )


def version_label(document: Document, manifest: Manifest) -> str:
    """How the header states what this text is: the answer must cite the version."""
    if document.status is Status.REVOKED:
        by = manifest.versions(document.revoked_by)
        who = by[0].designation if by else document.revoked_by
        return f"revogada pela {who} a partir de {document.revoked_from:%d/%m/%Y}"
    kind = (
        "texto consolidado"
        if document.version_kind is VersionKind.CONSOLIDATED
        else "texto original"
    )
    if document.status is Status.SUPERSEDED:
        return f"{kind}, superado pela versão consolidada"
    return f"{kind}, em vigor"


def chunk_document(
    document: Document,
    manifest: Manifest,
    segments: list[Segment],
    count_tokens: Callable[[str], int],
    budget: int = TOKEN_BUDGET,
) -> list[Chunk]:
    label = f"{document.designation} ({version_label(document, manifest)})"
    chunks: list[Chunk] = []
    unit: list[Segment] = []
    quotes: list[bool] = [False]  # the current unit transcribes another act's text

    def flush() -> None:
        if unit:
            kind = "amendment" if quotes[0] else "unit"
            chunks.extend(_pieces(document.doc_id, label, unit, count_tokens, budget, kind))
            unit.clear()
        quotes[0] = False

    for s in segments:
        if s.kind == "revocation_notice":
            flush()
            chunks.append(
                Chunk(
                    chunk_id=f"{document.doc_id}#{s.index:04d}",
                    doc_id=document.doc_id,
                    kind="notice",
                    citation=None,
                    segment_indexes=(s.index,),
                    text=f"{label}. {s.text}",
                )
            )
        elif s.kind in HEAD_KINDS:
            flush()
            unit.append(s)
        elif s.kind in BODY_KINDS and unit and s.locator is not None:
            unit.append(s)
        elif s.kind == QUOTED and unit and s.locator is not None:
            # The transcribed text belongs to the article that transcribes it.
            unit.append(s)
            quotes[0] = True
        else:
            flush()  # a heading or the frame ends the current unit
    flush()
    return chunks


AMENDMENT_NOTE = "texto transcrito por ato alterador; a redação em vigor é a da norma alterada"


def _header(label: str, head: Segment, kind: str = "unit") -> str:
    context = "; ".join(h for h in head.heading_path if h)
    parts = [label, context, head.citation or ""]
    if kind == "amendment":
        parts.append(AMENDMENT_NOTE)
    return ". ".join(p for p in parts if p) + "."


def _pieces(
    doc_id: str,
    label: str,
    unit: list[Segment],
    count_tokens: Callable[[str], int],
    budget: int,
    kind: str = "unit",
) -> list[Chunk]:
    """One chunk for the unit if it fits; otherwise greedy pieces, each repeating the head."""
    head, body = unit[0], unit[1:]
    header = _header(label, head, kind)
    base = f"{header} {head.text}"
    if count_tokens(" ".join([base, *(s.text for s in body)])) <= budget or not body:
        return [_chunk(doc_id, head, unit, base, body, kind=kind)]
    pieces: list[Chunk] = []
    current: list[Segment] = []
    for s in body:
        candidate = " ".join([base, *(x.text for x in current), s.text])
        if current and count_tokens(candidate) > budget:
            pieces.append(_chunk(doc_id, head, [head, *current], base, current, len(pieces), kind))
            current = []
        current.append(s)
    pieces.append(_chunk(doc_id, head, [head, *current], base, current, len(pieces), kind))
    return pieces


def _chunk(
    doc_id: str,
    head: Segment,
    members: list[Segment],
    base: str,
    body: list[Segment],
    piece: int | None = None,
    kind: str = "unit",
) -> Chunk:
    suffix = "" if piece is None else f".{piece}"
    return Chunk(
        chunk_id=f"{doc_id}#{head.index:04d}{suffix}",
        doc_id=doc_id,
        kind=kind,
        citation=head.citation,
        segment_indexes=tuple(s.index for s in members),
        text=" ".join([base, *(s.text for s in body)]),
    )
