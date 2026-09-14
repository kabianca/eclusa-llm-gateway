"""Run the generation cases live, once, through the whole lock, and keep everything.

Refuses unless the run is explicitly live (``ECLUSA_LIVE=1`` and the key), stops
before any call that would push the run's worst-case total over ``max_total_usd``,
appends every completion to the cassette, writes each response next to the case
for the author to grade, and writes the grades template if none exists — never
over an existing one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from eclusa.eval.generation import GenCaseSet, grades_template
from eclusa.service.ask import REQUESTED_OUTPUT_TOKENS, Gateway
from eclusa.service.budget import BudgetExceeded, estimate_input_tokens
from eclusa.service.provider import RecordingProvider


class NotLive(RuntimeError):
    """The recorder only runs live and on purpose."""


@dataclass(frozen=True)
class RecordedCase:
    case_id: str
    outcome: str
    audit_outcome: str
    cost_usd: float


def record(
    cases: GenCaseSet,
    gateway: Gateway,
    out_dir: Path,
    max_total_usd: float,
    today: date,
) -> list[RecordedCase]:
    if not isinstance(gateway.provider, RecordingProvider):
        raise NotLive(
            "the recorder needs a live, recording provider: set ECLUSA_LIVE=1 and the key"
        )
    responses_dir = out_dir / "responses"
    responses_dir.mkdir(parents=True, exist_ok=True)
    done: list[RecordedCase] = []
    spent_worst = 0.0
    for case in cases.cases:
        # The run-level net: the worst case of this call, on top of the worst cases so far.
        user = gateway.prompt.render_user(case.question, [], gateway.manifest)
        estimate = estimate_input_tokens(gateway.prompt.system, user) + 8 * 400  # k passages
        try:
            worst = gateway.budget.allowance(
                gateway.model, estimate, REQUESTED_OUTPUT_TOKENS
            ).worst_case_usd
        except BudgetExceeded as exc:
            worst = exc.ceiling_usd
        if spent_worst + worst > max_total_usd:
            raise RuntimeError(
                f"stopping before {case.id}: worst-case total US$ {spent_worst + worst:.4f} "
                f"would exceed --max-total-usd {max_total_usd:.4f}"
            )
        spent_worst += worst
        before = len(gateway.audit.records())
        response = gateway.ask(case.question, request_id=f"record-{case.id}-{today.isoformat()}")
        record_ = gateway.audit.records()[before]
        payload = {
            "case_id": case.id,
            "recorded_on": today.isoformat(),
            "response": json.loads(response.model_dump_json(exclude_none=True)),
            "audit_outcome": record_.outcome.value,
            "cost_usd": record_.cost_usd,
            "model": record_.model,
            "retrieved_chunk_ids": list(record_.retrieved_chunk_ids),
        }
        (responses_dir / f"{case.id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        done.append(
            RecordedCase(case.id, response.outcome.value, record_.outcome.value, record_.cost_usd)
        )
    grades_path = out_dir / "grades.json"
    if not grades_path.exists():
        grades_path.write_text(
            grades_template(cases).model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    return done
