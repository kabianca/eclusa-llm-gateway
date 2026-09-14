"""From segments to the passages that get embedded.

A citation must resolve to a passage that was actually retrieved, so a chunk is
first of all a set of segments — it knows which paragraphs it contains and what
they are called. What is embedded is those paragraphs with a short header naming
the act, its version status, the headings in force and the citation of the unit,
because "I - dos clientes;" means nothing on its own and "Circular nº 3.978,
art. 2º, parágrafo único" is half of what a question about it says.

The unit is the caput or the § with everything nested under it (incisos,
alíneas, items, notes). A unit longer than the token budget is split greedily,
and every piece repeats the head so that no piece is context-free. Two things
are deliberately not embedded: quoted blocks in amending acts — they duplicate
the consolidated text of another act, which already carries its provenance
marker, and would compete with it in retrieval — and the frame (preamble,
headings, signatures, attached notes), which is never citable as law. The
revocation notice is embedded on its own: it is the passage an answer about a
revoked act has to cite.
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
POLICY = "units-v1"  # bump when the chunking rules change: the index is derived from them


@dataclass(frozen=True)
class Chunk:
    chunk_id: str  # "<doc_id>#<index of the unit's head>[.<piece>]" — deterministic
    doc_id: str
    kind: Literal["unit", "notice"]
    citation: str | None  # of the unit's head; None for the revocation notice
    segment_indexes: tuple[int, ...]
    text: str  # header + paragraphs: exactly what is embedded


def is_embeddable(s: Segment) -> bool:
    """What retrieval can return: devices with a locator, and the revocation notice."""
    return s.kind == "revocation_notice" or (
        s.kind in HEAD_KINDS + BODY_KINDS and s.locator is not None
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

    def flush() -> None:
        if unit:
            chunks.extend(_pieces(document.doc_id, label, unit, count_tokens, budget))
            unit.clear()

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
        else:
            flush()  # a heading, a quoted block or the frame ends the current unit
    flush()
    return chunks


def _header(label: str, head: Segment) -> str:
    context = "; ".join(h for h in head.heading_path if h)
    parts = [label, context, head.citation or ""]
    return ". ".join(p for p in parts if p) + "."


def _pieces(
    doc_id: str,
    label: str,
    unit: list[Segment],
    count_tokens: Callable[[str], int],
    budget: int,
) -> list[Chunk]:
    """One chunk for the unit if it fits; otherwise greedy pieces, each repeating the head."""
    head, body = unit[0], unit[1:]
    header = _header(label, head)
    base = f"{header} {head.text}"
    if count_tokens(" ".join([base, *(s.text for s in body)])) <= budget or not body:
        return [_chunk(doc_id, head, unit, base, body)]
    pieces: list[Chunk] = []
    current: list[Segment] = []
    for s in body:
        candidate = " ".join([base, *(x.text for x in current), s.text])
        if current and count_tokens(candidate) > budget:
            pieces.append(_chunk(doc_id, head, [head, *current], base, current, len(pieces)))
            current = []
        current.append(s)
    pieces.append(_chunk(doc_id, head, [head, *current], base, current, len(pieces)))
    return pieces


def _chunk(
    doc_id: str,
    head: Segment,
    members: list[Segment],
    base: str,
    body: list[Segment],
    piece: int | None = None,
) -> Chunk:
    suffix = "" if piece is None else f".{piece}"
    return Chunk(
        chunk_id=f"{doc_id}#{head.index:04d}{suffix}",
        doc_id=doc_id,
        kind="unit",
        citation=head.citation,
        segment_indexes=tuple(s.index for s in members),
        text=" ".join([base, *(s.text for s in body)]),
    )
