"""The generation evaluation: recorded once, graded by hand, replayed forever.

See eval/generation/METHOD.md. This module holds the case schema, the
comparison of a response with its expectation (form: outcome, citations, key
phrases — never content, which is the author's grade), the recorder that runs
the cases live once, and the gate that replays them in recorded mode.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from eclusa.index.store import IndexStore
from eclusa.service.contract import Response
from eclusa.service.outcomes import Outcome, RefusalReason

SAVED_BY_THE_LOCK = (
    RefusalReason.CONTRACT_VIOLATION,
    RefusalReason.BUDGET_EXCEEDED,
    RefusalReason.PROVIDER_ERROR,
)

CASES_PATH = Path(__file__).resolve().parent.parent.parent / "eval" / "generation" / "cases.json"

Kind = Literal["answerable", "version", "partial", "refusal", "ambiguous", "revoked"]
Ref = tuple[str, str]  # (act_id or doc_id, unit citation or "notice")


class Expectation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Literal["answered", "partial", "refused"]
    must_cite: tuple[Ref, ...] = ()
    may_also_cite: tuple[Ref, ...] = ()
    answer_must_say: str | None = None  # a phrase the statements must contain
    gap_mentions: str | None = None  # a phrase the declared gap must contain
    refusal_reason: str | None = None


class GenCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: Kind
    question: str
    expected: Expectation
    why: str = Field(min_length=1)


class GenCaseSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    cases: tuple[GenCase, ...]


def load_cases(path: Path = CASES_PATH) -> GenCaseSet:
    return GenCaseSet.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass(frozen=True)
class Comparison:
    case_id: str
    mismatches: tuple[str, ...]  # empty: the response has the expected form

    @property
    def ok(self) -> bool:
        return not self.mismatches


def _matches(ref: Ref, doc_id: str, unit: str | None, kind: str) -> bool:
    scope, expected_unit = ref
    in_scope = doc_id == scope or doc_id.split("@")[0] == scope
    if expected_unit == "notice":
        return in_scope and kind == "notice"
    return in_scope and unit == expected_unit


def compare(case: GenCase, response: Response, store: IndexStore) -> Comparison:
    """Form only: outcome, citations, key phrases. Content is the author's grade."""
    exp = case.expected
    problems: list[str] = []
    if response.outcome.value != exp.outcome:
        problems.append(f"outcome {response.outcome.value}, expected {exp.outcome}")
    elif exp.outcome == "refused" and response.refusal_reason in SAVED_BY_THE_LOCK:
        # The caller sees a refusal either way, but a case that expects the model to refuse
        # is not satisfied by the contract catching a bad answer: one is the system working,
        # the other is the system being saved from itself.
        problems.append(f"refused by the lock ({response.refusal_reason.value}), not by the model")
    if exp.refusal_reason and (response.refusal_reason or "") != exp.refusal_reason:
        problems.append(f"refusal_reason {response.refusal_reason}, expected {exp.refusal_reason}")
    draft = response.draft
    if draft is None:
        if exp.must_cite or exp.answer_must_say or exp.gap_mentions:
            problems.append("no draft delivered, so nothing to cite or say")
        return Comparison(case.id, tuple(problems))
    by_id = {c.chunk_id: c for c in store.chunks}
    cited = []
    for statement in draft.statements:
        for c in statement.citations:
            chunk = by_id.get(c.chunk_id)
            if chunk is not None:
                cited.append((chunk.doc_id, chunk.citation, chunk.kind))
    for ref in exp.must_cite:
        if not any(_matches(ref, d, u, k) for d, u, k in cited):
            problems.append(f"must cite {ref[0]} {ref[1]}; cited {sorted(set(cited))}")
    text = " ".join(s.text for s in draft.statements).lower()
    if exp.answer_must_say and exp.answer_must_say.lower() not in text:
        problems.append(f"statements do not say {exp.answer_must_say!r}")
    gaps = " ".join(f"{g.text} {g.where or ''}" for g in draft.gaps).lower()
    if exp.gap_mentions and exp.gap_mentions.lower() not in gaps:
        problems.append(f"gaps do not mention {exp.gap_mentions!r}")
    return Comparison(case.id, tuple(problems))


class Grade(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: Literal["pass", "fail"] | None = None
    notes: str = ""


class Grades(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    graded_by: str | None = None
    graded_on: date | None = None
    grades: dict[str, Grade]


def grades_template(cases: GenCaseSet) -> Grades:
    return Grades(grades={c.id: Grade() for c in cases.cases})


@dataclass(frozen=True)
class GateResult:
    case_id: str
    comparison: Comparison
    grade: Grade | None
    audit_outcome: Outcome | None

    @property
    def ok(self) -> bool:
        return self.comparison.ok and self.grade is not None and self.grade.verdict == "pass"

    @property
    def needs_grade(self) -> bool:
        """Only an answer that already matches its expectation needs a human verdict.

        Where the form failed the case is failing whatever anyone writes, so grading it is
        busywork. Where the form matched, the answer looks right, and whether it *is* right
        is the one judgement no code here makes — which is also where a plausible wrong
        answer would otherwise pass.
        """
        return self.comparison.ok

    @property
    def status(self) -> str:
        if not self.comparison.ok:
            return "FAIL form"
        if self.grade is None or self.grade.verdict is None:
            return "UNGRADED"
        return "ok" if self.grade.verdict == "pass" else "FAIL grade"


def question_sha(question: str) -> str:
    return hashlib.sha256(question.encode("utf-8")).hexdigest()


def gate(cases: GenCaseSet, gateway, out_dir: Path) -> list[GateResult]:
    """Replay every case in recorded mode and hold it to its expectation and its grade.

    ``gateway.provider`` must be a RecordedProvider: a miss raises, it never records.
    """
    grades_path = out_dir / "grades.json"
    grades = (
        Grades.model_validate_json(grades_path.read_text(encoding="utf-8"))
        if grades_path.exists()
        else None
    )
    results: list[GateResult] = []
    for case in cases.cases:
        before = len(gateway.audit.records())
        response = gateway.ask(case.question, request_id=f"gate-{case.id}")
        audit_outcome = gateway.audit.records()[before].outcome
        grade = grades.grades.get(case.id) if grades else None
        results.append(
            GateResult(case.id, compare(case, response, gateway.index), grade, audit_outcome)
        )
    return results
