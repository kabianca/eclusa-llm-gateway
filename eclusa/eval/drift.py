"""The drift monitor: how far the live model has moved from the recordings.

This is the other evaluation flow, and the difference between it and the gate is
worth more than either of them. The gate runs on every push against recorded
responses: deterministic, no network, no key, no card — that is what holds the
badge, because CI that depends on a live model and a credit card does not run,
and a badge that depends on someone else's uptime lies.

This one is the opposite on purpose. It runs by hand, against the live model,
and it **never gates**. Model providers update models without notice; that is
information to observe, not a reason to fail a build. What it reports is
distance from the recordings, case by case: did the outcome change, did the
citations change, did the contract start or stop refusing — and how old the
recordings are, which is the number that says whether the comparison still means
anything.

It answers one question an auditor asks and a test suite cannot: *is the model
we recorded still the model we are running?*
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from eclusa.eval.generation import GenCaseSet
from eclusa.service.ask import Gateway
from eclusa.service.contract import Response


@dataclass(frozen=True)
class CaseDrift:
    case_id: str
    recorded_outcome: str
    live_outcome: str
    recorded_citations: tuple[str, ...]
    live_citations: tuple[str, ...]
    recorded_audit: str
    live_audit: str
    cost_usd: float

    @property
    def outcome_moved(self) -> bool:
        return self.recorded_outcome != self.live_outcome

    @property
    def citations_moved(self) -> bool:
        return set(self.recorded_citations) != set(self.live_citations)

    @property
    def moved(self) -> bool:
        return self.outcome_moved or self.citations_moved or self.recorded_audit != self.live_audit


def citations_of(response: dict) -> tuple[str, ...]:
    """What the answer rests on, as a stable set: document and device, order ignored."""
    draft = response.get("draft") or {}
    return tuple(
        sorted(
            f"{c['doc_id']}·{c['locator']}"
            for s in draft.get("statements", [])
            for c in s["citations"]
        )
    )


def compare_to_recording(
    case_id: str, recorded: dict, live: Response, live_audit: str, cost: float
) -> CaseDrift:
    return CaseDrift(
        case_id=case_id,
        recorded_outcome=recorded["response"]["outcome"],
        live_outcome=live.outcome.value,
        recorded_citations=citations_of(recorded["response"]),
        live_citations=citations_of(json.loads(live.model_dump_json())),
        recorded_audit=recorded["audit_outcome"],
        live_audit=live_audit,
        cost_usd=cost,
    )


def run(cases: GenCaseSet, gateway: Gateway, out_dir: Path, today: date) -> dict:
    """Ask the live model the frozen questions and measure the distance. Never raises on drift."""
    responses_dir = out_dir / "responses"
    drifts: list[CaseDrift] = []
    recorded_on: set[str] = set()
    for case in cases.cases:
        path = responses_dir / f"{case.id}.json"
        if not path.exists():
            continue
        recorded = json.loads(path.read_text(encoding="utf-8"))
        recorded_on.add(recorded["recorded_on"])
        before = len(gateway.audit.records())
        live = gateway.ask(case.question, request_id=f"drift-{case.id}-{today.isoformat()}")
        record = gateway.audit.records()[before]
        drifts.append(
            compare_to_recording(case.id, recorded, live, record.outcome.value, record.cost_usd)
        )
    oldest = min(recorded_on) if recorded_on else None
    age_days = (today - date.fromisoformat(oldest)).days if oldest else None
    return {
        "ran_on": today.isoformat(),
        "recordings_made_on": sorted(recorded_on),
        "recordings_age_days": age_days,
        "model": gateway.model,
        "cases": len(drifts),
        "moved": sum(d.moved for d in drifts),
        "outcome_moved": sum(d.outcome_moved for d in drifts),
        "citations_moved": sum(d.citations_moved for d in drifts),
        "cost_usd": round(sum(d.cost_usd for d in drifts), 5),
        "results": [asdict(d) for d in drifts],
    }
