"""Version-aware retrieval: the layer between the index and the prompt.

The raw index does what embeddings do: it returns the nearest chunks. On a corpus
where the same act exists in two near-identical versions, "nearest" is not "the
law". Measured before this layer existed (eval/retrieval/results-before.json):
the expected unit was found in 92% of the cases, but the version in force ranked
first in 25% — and in none of the provisions whose text did not change, because
identical texts tie and the tie-break by chunk id picks "@v1" before "@v5". A
tie is a decision; that one was wrong for versions. The revocation notice never
came along with revoked text.

What this layer decides, in order:

1. Search a pool wider than k, then group chunks by (act, unit). One unit of one
   act is one candidate, whatever number of versions it has.
2. Rank groups: acts in force first, revoked acts after — unless the question
   names the revoked act, in which case it is what was asked about. Within a
   tier, by best score, then by act and unit for a deterministic order.
3. Inside a group, the version in force comes first. The superseded version is
   emitted right after it only when its text differs — that is the history an
   answer may need to mention ("the original wording said July"); an identical
   superseded text adds nothing but noise.
4. When a revoked act enters the result, its revocation notice enters with it,
   so the contract's "revoked text must cite its revocation" can be satisfied.

Everything here is deterministic given the index, and nothing here changes a
score: the layer reorders and filters, so the "after" number in the evaluation
measures exactly these four decisions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from eclusa.corpus.manifest import Manifest, Status
from eclusa.index.chunks import Chunk
from eclusa.index.embedding import Embedder
from eclusa.index.store import Hit, IndexStore

NUMBER = re.compile(r"\b(\d{1,2}\.\d{3}|\d{3,5})\b")  # "3.461", "3461", "119", "4.001"

VERSION_PRIORITY = {Status.IN_FORCE: 0, Status.REVOKED: 1, Status.SUPERSEDED: 2}


@dataclass(frozen=True)
class Group:
    act_id: str
    unit: str  # the unit citation, or "notice"
    best: float
    tier: int
    hits: tuple[Hit, ...]  # in version priority order


def mentioned_acts(question: str, manifest: Manifest) -> set[str]:
    """Acts whose number appears in the question: 'Circular 3.461' names circular-3461-2009."""
    numbers = {int(n.replace(".", "")) for n in NUMBER.findall(question)}
    return {d.act_id for d in manifest.documents if d.number in numbers}


def body_of(chunk: Chunk) -> str:
    """The chunk text without its header, so two versions can be compared on wording."""
    marker = f"{chunk.citation}. " if chunk.citation else ". "
    return chunk.text.split(marker, 1)[-1]


def retrieve(
    question: str,
    store: IndexStore,
    embedder: Embedder,
    manifest: Manifest,
    k: int = 8,
) -> list[Chunk]:
    ranking = store.search(embedder.embed_query(question), k=len(store.chunks))
    named = mentioned_acts(question, manifest)
    groups = _group(ranking, manifest, named)
    notices = {c.doc_id: c for c in store.chunks if c.kind == "notice"}
    out: list[Chunk] = []
    seen: set[str] = set()
    for group in groups:
        for chunk in _versions_to_emit(group, manifest):
            _emit(out, seen, chunk)
            if manifest.by_id(chunk.doc_id).status is Status.REVOKED:
                notice = notices.get(chunk.doc_id)
                if notice is not None:
                    _emit(out, seen, notice)
            if len(out) >= k:
                return out[:k]
    return out[:k]


def _group(ranking: list[Hit], manifest: Manifest, named: set[str]) -> list[Group]:
    """One group per (act, unit); inside it, each document's best-scoring piece."""
    best_piece: dict[tuple[str, str], dict[str, Hit]] = {}
    for hit in ranking:  # score-descending: the first piece seen per document is its best
        if hit.chunk.kind == "notice":
            continue  # notices are attached by rule, never ranked as candidates
        act_id = manifest.by_id(hit.chunk.doc_id).act_id
        key = (act_id, hit.chunk.citation or "")
        best_piece.setdefault(key, {}).setdefault(hit.chunk.doc_id, hit)
    groups = []
    for (act_id, unit), per_doc in best_piece.items():
        ordered = sorted(
            per_doc.values(),
            key=lambda h: (
                VERSION_PRIORITY[manifest.by_id(h.chunk.doc_id).status],
                h.chunk.chunk_id,
            ),
        )
        revoked = manifest.current(act_id) is None
        tier = 1 if revoked and act_id not in named else 0
        best = max(h.score for h in per_doc.values())
        groups.append(Group(act_id, unit, best, tier, tuple(ordered)))
    return sorted(groups, key=lambda g: (g.tier, -g.best, g.act_id, g.unit))


def _versions_to_emit(group: Group, manifest: Manifest) -> list[Chunk]:
    first = group.hits[0].chunk
    out = [first]
    for hit in group.hits[1:]:
        status = manifest.by_id(hit.chunk.doc_id).status
        if status is Status.SUPERSEDED and body_of(hit.chunk) == body_of(first):
            continue  # identical history is noise, not information
        out.append(hit.chunk)
    return out


def _emit(out: list[Chunk], seen: set[str], chunk: Chunk) -> None:
    if chunk.chunk_id not in seen:
        seen.add(chunk.chunk_id)
        out.append(chunk)
