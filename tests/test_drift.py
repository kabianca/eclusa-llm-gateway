"""The drift monitor measures distance from the recordings and never gates.

No live call here: the comparison is a pure function over a recorded response and a
live one, which is the whole of what the monitor decides.
"""

import json
from datetime import date
from pathlib import Path

from eclusa.eval.drift import CaseDrift, citations_of, compare_to_recording
from eclusa.service.contract import Citation, Draft, Response, Statement
from eclusa.service.outcomes import Outcome, RefusalReason


def answered(locator: str = "art. 70, caput", doc: str = "circular-3978-2020@v5") -> Response:
    return Response(
        request_id="r",
        outcome=Outcome.ANSWERED,
        draft=Draft(
            outcome="answered",
            statements=(
                Statement(
                    text="Entra em vigor em 1º/10/2020.",
                    citations=(Citation(doc_id=doc, chunk_id=f"{doc}#0444", locator=locator),),
                ),
            ),
        ),
    )


def recorded_payload(response: Response, audit: str = "answered") -> dict:
    return {
        "recorded_on": "2026-10-03",
        "response": json.loads(response.model_dump_json(exclude_none=True)),
        "audit_outcome": audit,
    }


def test_citations_are_compared_as_a_set_of_document_and_device():
    r = json.loads(answered().model_dump_json())
    assert citations_of(r) == ("circular-3978-2020@v5·art. 70, caput",)
    assert citations_of({"draft": None}) == (), "a refusal rests on nothing"


def test_nothing_moved_when_the_live_answer_matches_the_recording():
    d = compare_to_recording(
        "version-70", recorded_payload(answered()), answered(), "answered", 0.002
    )
    assert not d.moved and not d.outcome_moved and not d.citations_moved


def test_a_changed_outcome_is_drift():
    refused = Response(
        request_id="r", outcome=Outcome.REFUSED, refusal_reason=RefusalReason.NOT_IN_CORPUS
    )
    d = compare_to_recording("version-70", recorded_payload(answered()), refused, "refused", 0.001)
    assert d.outcome_moved and d.moved
    assert d.live_citations == () and d.recorded_citations != ()


def test_the_same_outcome_resting_on_other_passages_is_drift_too():
    d = compare_to_recording(
        "version-70",
        recorded_payload(answered()),
        answered(locator="art. 69, caput"),
        "answered",
        0.002,
    )
    assert not d.outcome_moved, "the caller sees the same kind of answer"
    assert d.citations_moved and d.moved, "but it rests on a different provision"


def test_the_contract_changing_its_mind_is_drift():
    # Same outcome to the caller and the same citations, but the lock refused this time.
    d = CaseDrift(
        case_id="x",
        recorded_outcome="refused",
        live_outcome="refused",
        recorded_citations=(),
        live_citations=(),
        recorded_audit="refused",
        live_audit="contract_violation",
        cost_usd=0.0,
    )
    assert d.moved and not d.outcome_moved and not d.citations_moved


def test_a_report_says_how_old_the_recordings_are(
    manifest, corpus_dir, small_index, embedder, tmp_path
):
    from eclusa.eval.drift import run
    from eclusa.eval.generation import load_cases
    from eclusa.service.ask import Gateway
    from eclusa.service.audit import AuditLog
    from eclusa.service.budget import Budget
    from eclusa.service.prompts import Prompt
    from eclusa.service.provider import Completion, RecordingProvider

    class Live:
        model = "gpt-5.4-mini-2026-03-17"

        def complete(self, request):
            payload = {
                "outcome": "refused",
                "statements": [],
                "gaps": [],
                "refusal_reason": "not_in_corpus",
                "refusal_note": None,
            }
            return Completion(
                text=json.dumps(payload),
                model=self.model,
                input_tokens=10,
                output_tokens=5,
                live=True,
            )

    out = tmp_path / "gen"
    (out / "responses").mkdir(parents=True)
    cases = load_cases()
    one = cases.model_copy(update={"cases": cases.cases[:1]})
    case_id = one.cases[0].id
    (out / "responses" / f"{case_id}.json").write_text(
        json.dumps(recorded_payload(answered())), encoding="utf-8"
    )
    gateway = Gateway(
        manifest=manifest,
        manifest_path=corpus_dir / "manifest.json",
        corpus_dir=corpus_dir,
        index=small_index,
        embedder=embedder,
        provider=RecordingProvider(Live(), tmp_path / "drift.jsonl", today=date(2026, 11, 2)),
        budget=Budget(0.05),
        audit=AuditLog(tmp_path / "trail.jsonl"),
        prompt=Prompt.load("answer-v1"),
    )
    report = run(one, gateway, out, date(2026, 11, 2))
    assert report["cases"] == 1 and report["moved"] == 1
    assert report["recordings_age_days"] == 30, "the number that says whether the comparison holds"
    assert report["recordings_made_on"] == ["2026-10-03"]
    assert Path(tmp_path / "drift.jsonl").exists(), "the live answers are kept as evidence"
