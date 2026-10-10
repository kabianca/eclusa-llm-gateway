"""Turn a captured document into a list of normalised paragraphs.

Two routes feed the corpus and they must come out in the same form, because the
project's main test compares two versions of the same act that arrive by
different routes: the original wording from the BCB endpoint's HTML, the
consolidated wording from a PDF. If the two routes disagreed on whitespace,
quotation marks or where a paragraph ends, a failed version test could not tell
version handling from extraction noise. So both routes produce one paragraph per
normative device (caput, §, inciso, alínea, heading) and an article that did not
change between versions must come out byte-identical from either route.

What the probe on real documents found, and what this module does about it:

- ``pdftotext -layout`` follows two conventions in the same document. In body
  text the first line of a paragraph is indented and continuation lines start
  at column 0, with no blank line between paragraphs ("I - dos clientes;" is
  followed directly by "II - da instituição;"): an indented line opens a
  paragraph. Inside a quoted block — an amending act quoting whole articles —
  every line shares the block's indent and paragraphs are separated by blank
  lines: only a blank line (or a deeper indent) opens one. Which convention
  applies is decided by the quote state — an opening ``“`` not yet closed by
  ``”``, or an odd number of straight ``"`` (the 2010–2017 acts quote with
  straight marks). Blank lines at the top of a page never count — pages break
  in the middle of paragraphs.
- Long centred headings start at column 0 too; headings are recognised by
  being upper-case and get their own paragraph, merging with an adjacent
  heading line ("DA POLÍTICA ... DO" / "TERRORISMO").
- A running footer closes the pages, in four layouts across the corpus: the
  act's designation plus "Página N de M" (2020 onwards, absent on page 1), the
  designation plus a bare page number (2009), the designation alone (2010),
  the designation with a full stop (2012). Repetition cannot be relied on: a
  document of one or two pages has no majority. The rule is positional and
  document-specific instead — **the last non-blank line of a page is a footer
  if it starts with the act's own designation** ("Circular nº 3.517", with or
  without the thousands separator) **or is a bare page mark**. A one-page
  document has no footer and nothing is removed. Pages break in the middle of
  an article, so footers go before pages are joined.
- The last article is followed by the document's frame: a dateline in older
  acts, the signature block, in PDFs the note "Este texto não substitui o
  publicado no DOU...", and in Instruções Normativas the technical note that
  justified the act ("NOTA 388/2026-BCB/DENOR..."), with its own numbered
  paragraphs. None of it is the article. The rule is anchored to position and
  to the start of the frame: after the last article's caput, the first
  paragraph that looks like frame — a fixed closing phrase, a heading-like
  name line, or an unpunctuated line that is not a device — opens the frame,
  and everything after it belongs to the frame. Nothing before the last
  article is ever touched.
- Section titles come in two lines — "Seção I" and, in title case, "Dos
  Procedimentos..." — and are headings, not part of the preceding article; a
  new article inserted at the end of a section (23-A) would otherwise change
  who owns the title.
- Compound words break at the margin on their real hyphen ("Procuradores-
  Gerais"). Official PDFs do not hyphenate words, so a trailing hyphen is
  always part of the word and the continuation is joined without a space.
- Articles quoted from other acts are not headers. Amending acts are made of
  them: "Art. 1º A Circular 3.461 passa a vigorar com as seguintes
  alterações: “Art. 4º ...”". The quotation mark in front of ``Art.`` (curly or
  straight) is the first guard; the second is the quote state — a block that
  opened with ``“`` on a section title ("“Pessoas Expostas Politicamente")
  keeps every ``Art.`` inside it from being a header until ``”`` closes it.
- A revoked act's consolidation opens with "Documento normativo revogado, a
  partir de ..."; on some layouts the line follows the title at column 0 and
  would be joined to it. It is always its own paragraph.
"""

from __future__ import annotations

import html as html_lib
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

from eclusa.corpus.manifest import Document, TextSource

PAGE_MARK = re.compile(r"^(Página \d+ de \d+|\d{1,3})$")
CLOSING = re.compile(r"^(Este texto não substitui|Brasília, \d+ de \w+ de \d{4}\.$)")
REVOCATION = re.compile(r"^Documento normativo revogado")
SENTENCE_END = re.compile(r"[.;:)”\"]$")
DEVICE = re.compile(
    r"^(§ \d|Parágrafo único|[IVXL]+ -|[a-z]{1,2}\) |\d+\. )"
)  # § inciso alínea item
ARTICLE = re.compile(r"^Art\. (?P<number>\d+)(?:º)?(?P<suffix>-[A-Z])?(?:[ .]|$)")
OPENS_QUOTE = re.compile(r"^[“\"]")
CHAPTER = re.compile(r"^(CAPÍTULO|TÍTULO|LIVRO|ANEXO)\b")
SECTION = re.compile(r"^(Seção|Subseção)\b")
TAG = re.compile(r"<[^>]+>")
BLOCK_END = re.compile(r"</p\s*>|<br\s*/?>", re.IGNORECASE)


class QuoteState:
    """Inside a quotation or not.

    ``“`` opens and ``”`` closes; a straight ``"`` closes if a quotation is open and
    opens otherwise. One depth for both, because the acts mix them: Circular 3.654
    opens a block with ``"Art. 10.`` and closes it with ``”``.
    """

    def __init__(self) -> None:
        self.depth = 0

    def update(self, text: str) -> None:
        for char in text:
            if char == "“":
                self.depth += 1
            elif char == "”":
                self.depth = max(0, self.depth - 1)
            elif char == '"':
                self.depth = self.depth - 1 if self.depth else 1

    @property
    def inside(self) -> bool:
        return self.depth > 0


class ExtractionError(RuntimeError):
    """Raised, never skipped: a missing extractor must fail the suite, not thin it."""


HTML_EXTRACTOR = "html (no external tool)"  # the HTML route depends on this module alone


def pdftotext_version() -> str:
    """The installed poppler, e.g. '25.03.0'. It is part of the pipeline and is recorded.

    Two poppler majors do not promise the same text for the same PDF, so the version
    that produced the committed text lives in the manifest and is asserted before the
    text is compared: a mismatch is then named as such, not left as unexplained bytes.
    """
    if shutil.which("pdftotext") is None:
        raise ExtractionError(
            "pdftotext (poppler-utils) is not installed; the PDF route cannot run"
        )
    result = subprocess.run(["pdftotext", "-v"], capture_output=True, text=True, check=False)
    m = re.search(r"pdftotext version (\S+)", result.stderr + result.stdout)
    if m is None:
        raise ExtractionError(f"cannot read the pdftotext version from: {result.stderr!r}")
    return m.group(1)


def extractor_version(route: TextSource) -> str:
    """What the manifest records for a text: 'pdftotext 25.03.0', or the HTML marker."""
    return f"pdftotext {pdftotext_version()}" if route is TextSource.PDF else HTML_EXTRACTOR


def normalise(line: str) -> str:
    """The common form both routes are reduced to before comparison or segmentation."""
    line = line.replace("\xa0", " ").replace("\u200b", "")  # nbsp; zero-width space
    line = line.replace("°", "º")  # degree sign used as an ordinal
    line = unicodedata.normalize("NFC", line)
    return re.sub(r"[ \t]+", " ", line).strip()


SMALL_WORDS = frozenset(
    "a à ao aos as às com da das de do dos e em na nas no nos o os ou para por sem sobre".split()
)


def is_heading(paragraph: str) -> bool:
    """Chapter and section titles: upper-case lines, "Seção N" lines, and short unpunctuated
    Title-Case lines ("Especial Atenção", "Dos Procedimentos de Monitoramento"). Never part of
    an article body."""
    has_letters = re.search(r"[A-ZÀ-Ü]", paragraph) is not None
    has_lower = re.search(r"[a-zà-ü]", paragraph) is not None
    if has_letters and not has_lower:
        return True
    if SECTION.match(paragraph):
        return True
    return _title_case_line(paragraph)


TITLE_END = re.compile(r"[.;:,\-]$")


def _title_case_line(paragraph: str) -> bool:
    # Section titles run long ("Registros de Depósitos em Cheque, Liquidação de Cheques
    # Depositados em Outra Instituição Financeira e da Utilização de ..."), so the cap is
    # generous; what protects body text is that its paragraphs end with punctuation.
    words = [w.lstrip("(") for w in paragraph.split()]  # "(PEP)" is a capitalised word
    if not 1 <= len(words) <= 24 or TITLE_END.search(paragraph):
        return False
    if ARTICLE.match(paragraph) or DEVICE.match(paragraph) or OPENS_QUOTE.match(paragraph):
        return False
    return all(w[:1].isupper() or w in SMALL_WORDS for w in words) and words[0][:1].isupper()


def article_label(paragraph: str) -> str | None:
    """'23-A' for a paragraph opening article 23-A; None otherwise. Quoting is the caller's call."""
    m = ARTICLE.match(paragraph)
    if m is None:
        return None
    return m["number"] + (m["suffix"] or "")


def paragraphs_from_html(raw_html: str) -> list[str]:
    """The BCB endpoint's ``Texto``: one ``<p>`` per device, entities encoded, nbsp after 'Art.'."""
    # Newlines inside the markup are insignificant whitespace (Word-exported HTML
    # wraps sentences); only </p> and <br> end a paragraph.
    text = re.sub(r"\s+", " ", raw_html)
    text = BLOCK_END.sub("\n", text)
    text = html_lib.unescape(TAG.sub("", text))
    return [p for p in (normalise(line) for line in text.split("\n")) if p]


def paragraphs_from_html_file(path: Path) -> list[str]:
    """The endpoint's ``Texto`` field as captured by the collector."""
    return paragraphs_from_html(Path(path).read_text(encoding="utf-8"))


def paragraphs_from_pdf(path: Path, designation: str | None = None) -> list[str]:
    """Consolidated text via poppler's ``pdftotext -layout``; the module docstring has the rules.

    ``designation`` is how the act names itself ("Circular nº 3.978"); it is what
    the running footer starts with. Without it only bare page marks are removed.
    """
    if shutil.which("pdftotext") is None:
        raise ExtractionError(
            "pdftotext (poppler-utils) is not installed; the PDF route cannot run"
        )
    result = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    return _reflow(_without_footers(result.stdout, designation))


def footer_pattern(designation: str | None) -> re.Pattern[str]:
    """What a page-closing line must look like to be a footer for this act."""
    if designation is None:
        return PAGE_MARK
    # "Circular nº 3.517" also appears as "Circular nº 3517" in older footers.
    loose = re.escape(designation).replace(r"\.", r"\.?")
    return re.compile(rf"^(?:{loose}\b.*|Página \d+ de \d+|\d{{1,3}})$")


def _without_footers(layout_text: str, designation: str | None) -> list[list[str]]:
    """The document as pages of lines, each page's closing footer removed."""
    footer = footer_pattern(designation)
    pages: list[list[str]] = []
    for page in layout_text.split("\f"):
        lines = page.split("\n")
        last = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip()), None)
        if last is not None and footer.match(normalise(lines[last])):
            del lines[last]
        pages.append(lines)
    return pages


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _upper(text: str) -> bool:
    """An upper-case title line, as opposed to a Title-Case one (which never wraps)."""
    return re.search(r"[A-ZÀ-Ü]", text) is not None and re.search(r"[a-zà-ü]", text) is None


def _reflow(pages: list[list[str]]) -> list[str]:
    paragraphs: list[str] = []
    previous_upper = False
    previous_breaks = False  # a CAPÍTULO or Seção line: what follows is always a new paragraph
    previous_indent = 0
    quotes = QuoteState()  # inside a quotation the block convention applies
    for page in pages:
        blank_before = False  # blank lines at the top of a page are not paragraph breaks
        seen_text = False
        for line in page:
            if not line.strip():
                blank_before = seen_text
                continue
            seen_text = True
            text = normalise(line)
            indent = _indent(line)
            # A Title-Case line is a heading only where a heading can be: indented (they
            # are centred) or after a blank line. At column 0 it is a continuation line
            # that happens to be full of proper nouns ("Procurador-Geral da Justiça...").
            heading = _upper(text) or SECTION.match(text) is not None
            heading = heading or ((indent > 0 or blank_before) and _title_case_line(text))
            if quotes.inside:
                opens = blank_before or indent > previous_indent
            else:
                opens = blank_before or indent > 0
            opens = opens or REVOCATION.match(text) is not None
            label = CHAPTER.match(text) is not None or SECTION.match(text) is not None
            wraps = _upper(text) and previous_upper and not previous_breaks and not label
            if wraps and not paragraphs[-1].endswith(":"):
                # a centred title wrapped onto two lines; never a label, never after "RESOLVE:"
                paragraphs[-1] = f"{paragraphs[-1]} {text}"
            elif opens or heading or previous_breaks or not paragraphs:
                paragraphs.append(text)
            elif paragraphs[-1].endswith("-"):
                paragraphs[-1] = f"{paragraphs[-1]}{text}"
            else:
                paragraphs[-1] = f"{paragraphs[-1]} {text}"
            quotes.update(text)
            previous_upper = _upper(text)
            previous_breaks = CHAPTER.match(text) is not None or SECTION.match(text) is not None
            previous_indent = indent
            blank_before = False
    return paragraphs


def paragraphs_from_capture(route: TextSource, raw: Path, designation: str) -> list[str]:
    """Extract a captured file by its route. This is the only place the route is dispatched."""
    if route is TextSource.PDF:
        return paragraphs_from_pdf(raw, designation=designation)
    return paragraphs_from_html_file(raw)


def paragraphs_of(document: Document, corpus_dir: Path) -> list[str]:
    """Re-extract a manifest document from its raw capture (the committed text should equal it)."""
    raw = Path(corpus_dir) / document.raw_path
    return paragraphs_from_capture(document.text_source, raw, document.designation)


def save_paragraphs(paragraphs: list[str], path: Path) -> None:
    """One paragraph per line; the committed form the index reads and reviewers diff."""
    if any("\n" in p for p in paragraphs):
        raise ExtractionError("a paragraph contains a newline; the one-per-line format would lie")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(paragraphs) + "\n", encoding="utf-8")


def load_paragraphs(path: Path) -> list[str]:
    return Path(path).read_text(encoding="utf-8").splitlines()


def articles(paragraphs: list[str]) -> dict[str, list[str]]:
    """Article label -> its paragraphs, headings and closing matter excluded.

    Insertion order is document order. The title-case line after "Seção N" is the
    section's title and counts as a heading.
    """
    labels = article_labels(paragraphs)
    last = max((i for i, label in enumerate(labels) if label), default=None)
    end = len(paragraphs) if last is None else frame_start(paragraphs, last)
    bodies: dict[str, list[str]] = {}
    current: str | None = None
    after_section = False
    for p, label in zip(paragraphs[:end], labels[:end], strict=True):
        if label is not None:
            current = label
            bodies[current] = []
        heading = label is None and (is_heading(p) or after_section)
        after_section = SECTION.match(p) is not None
        if current is not None and not heading:
            bodies[current].append(p)
    return bodies


def article_labels(paragraphs: list[str]) -> list[str | None]:
    """Per paragraph, the article it opens — or None, including for quoted articles."""
    labels: list[str | None] = []
    quotes = QuoteState()
    for p in paragraphs:
        labels.append(None if quotes.inside or OPENS_QUOTE.match(p) else article_label(p))
        quotes.update(p)
    return labels


def frame_start(paragraphs: list[str], last_article: int) -> int:
    """Index of the first paragraph of the document's frame after the last article.

    Anchored to position: only paragraphs after the last article's caput are candidates,
    and the first one that looks like frame opens it — everything after belongs to the
    frame (signatures, DOU note, an attached technical note). ``len(paragraphs)`` if
    the document ends with the last article.
    """
    for i in range(last_article + 1, len(paragraphs)):
        if _looks_like_frame(paragraphs[i]):
            return i
    return len(paragraphs)


def _looks_like_frame(paragraph: str) -> bool:
    # A dateline or the DOU note; a name line (Title Case or upper case, which after the
    # last article cannot be a section title); or an unpunctuated line that is not a
    # device — including the long garbled lines a two-column signature block produces.
    if CLOSING.match(paragraph) or is_heading(paragraph):
        return True
    return SENTENCE_END.search(paragraph) is None and DEVICE.match(paragraph) is None
