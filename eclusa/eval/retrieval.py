"""The retrieval evaluation, as defined in eval/retrieval/METRIC.md.

Retrieval is evaluated on its own: a retrieval that returns the wrong passages
must fail its own measurement, not be masked by a model that answers well anyway.
The cases and the metrics were frozen before the retrieval layer was changed; this
module only computes them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from eclusa.corpus.manifest import Manifest, Status
from eclusa.index.chunks import Chunk
from eclusa.index.embedding import Embedder
from eclusa.index.store import IndexStore

CASES_PATH = Path(__file__).resolve().parent.parent.parent / "eval" / "retrieval" / "cases.json"

Kind = Literal["changed", "unchanged", "topic", "names_revoked", "asks_original"]


class Case(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: Kind
    question: str
    expected_act: str
    units: tuple[str, ...] = Field(min_length=1)
    revoked_act: str | None = None  # kind topic: the competing revoked act


class CaseSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    k: int
    cases: tuple[Case, ...]


def load_cases(path: Path = CASES_PATH) -> CaseSet:
    return CaseSet.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass(frozen=True)
class CaseResult:
    id: str
    kind: Kind
    hit: bool
    in_force_first: bool | None
    mrr_in_force: float | None
    revoked_below_current: bool | None
    notice_with_revoked: bool | None
    named_first: bool | None
    superseded_reachable: bool | None
    top: tuple[str, ...]  # "doc_id citation" of the top-k, for reading


def act_of(chunk: Chunk) -> str:
    return chunk.doc_id.split("@")[0]


def evaluate_case(case: Case, ranked: list[Chunk], manifest: Manifest) -> CaseResult:
    """Apply the metrics of METRIC.md to one case's ranked chunks (already cut at k)."""
    matches = [
        (rank, c)
        for rank, c in enumerate(ranked, start=1)
        if act_of(c) == case.expected_act and c.citation in case.units
    ]
    superseded = [
        (r, c) for r, c in matches if manifest.by_id(c.doc_id).status is Status.SUPERSEDED
    ]
    hit = bool(superseded) if case.kind == "asks_original" else bool(matches)
    in_force_first = mrr = None
    if case.kind in ("changed", "unchanged"):
        in_force_first = hit and manifest.by_id(matches[0][1].doc_id).status is Status.IN_FORCE
        current = [r for r, c in matches if manifest.by_id(c.doc_id).status is Status.IN_FORCE]
        mrr = 1.0 / current[0] if current else 0.0
    below = None
    if case.kind == "topic":
        first_current = next(
            (r for r, c in enumerate(ranked, 1) if act_of(c) == case.expected_act), None
        )
        first_revoked = next(
            (r for r, c in enumerate(ranked, 1) if act_of(c) == case.revoked_act), None
        )
        below = first_current is not None and (
            first_revoked is None or first_current < first_revoked
        )
    notice = named_first = None
    if case.kind == "names_revoked":
        revoked_present = any(act_of(c) == case.expected_act for c in ranked)
        has_notice = any(act_of(c) == case.expected_act and c.kind == "notice" for c in ranked)
        notice = (not revoked_present) or has_notice
        named_first = bool(ranked) and act_of(ranked[0]) == case.expected_act
    reachable = bool(superseded) if case.kind == "asks_original" else None
    return CaseResult(
        id=case.id,
        kind=case.kind,
        hit=hit,
        in_force_first=in_force_first,
        mrr_in_force=mrr,
        revoked_below_current=below,
        notice_with_revoked=notice,
        named_first=named_first,
        superseded_reachable=reachable,
        top=tuple(f"{c.doc_id} {c.citation or '(notice)'}" for c in ranked),
    )


def aggregate(results: list[CaseResult]) -> dict[str, float | int]:
    def frac(values: list[bool | float]) -> float | None:
        return round(sum(values) / len(values), 4) if values else None

    out: dict[str, float | int | None] = {
        "cases": len(results),
        "hit@k": frac([r.hit for r in results]),
        "in_force_first": frac([r.in_force_first for r in results if r.in_force_first is not None]),
        "mrr_in_force": frac([r.mrr_in_force for r in results if r.mrr_in_force is not None]),
        "revoked_below_current": frac(
            [r.revoked_below_current for r in results if r.revoked_below_current is not None]
        ),
        "notice_with_revoked": frac(
            [r.notice_with_revoked for r in results if r.notice_with_revoked is not None]
        ),
        "named_first": frac([r.named_first for r in results if r.named_first is not None]),
        "superseded_reachable": frac(
            [r.superseded_reachable for r in results if r.superseded_reachable is not None]
        ),
    }
    for kind in ("changed", "unchanged", "topic", "names_revoked", "asks_original"):
        subset = [r for r in results if r.kind == kind]
        out[f"hit@k[{kind}]"] = frac([r.hit for r in subset])
        if kind in ("changed", "unchanged"):
            out[f"in_force_first[{kind}]"] = frac([r.in_force_first for r in subset])
    return {k: v for k, v in out.items() if v is not None}


def run(
    cases: CaseSet,
    store: IndexStore,
    embedder: Embedder,
    manifest: Manifest,
    search=None,
) -> tuple[dict, list[CaseResult]]:
    """Evaluate every case. ``search(question) -> list[Chunk]`` lets a retrieval layer be
    measured with the same cases; by default the raw index is used."""
    if search is None:

        def search(question: str) -> list[Chunk]:
            return [h.chunk for h in store.search(embedder.embed_query(question), k=cases.k)]

    results = [
        evaluate_case(case, search(case.question)[: cases.k], manifest) for case in cases.cases
    ]
    summary = {
        "k": cases.k,
        "index": {key: store.meta.get(key) for key in ("model_revision", "chunk_policy", "chunks")},
        "metrics": aggregate(results),
    }
    return summary, results
