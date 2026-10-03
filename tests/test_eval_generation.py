"""The generation evaluation's machinery, without any live call: the cases point at real
provisions, the comparison holds a response to its expectation in form only, the recorder
refuses to run unless explicitly live and stops on the run-level cap, and the gate replays
recordings against the author's grades. The pytest gate over the real recordings is added
together with the recordings, once the author has run and graded them."""

import json
from datetime import date
from pathlib import Path

import pytest

from eclusa.eval import generation as gen
from eclusa.eval.record import NotLive, record
from eclusa.index.chunks import chunk_document
from eclusa.ingest.extract import load_paragraphs
from eclusa.ingest.segment import segment
from eclusa.service.ask import Gateway
from eclusa.service.audit import AuditLog
from eclusa.service.budget import Budget
from eclusa.service.contract import Citation, Draft, Gap, Response, Statement
from eclusa.service.models import GENERATION_MODEL
from eclusa.service.outcomes import Outcome, RefusalReason
from eclusa.service.prompts import Prompt
from eclusa.service.provider import Completion, RecordedProvider, RecordingProvider


def test_cases_are_well_formed_and_point_at_real_provisions(manifest, corpus_dir):
    cases = gen.load_cases()
    ids = [c.id for c in cases.cases]
    assert len(ids) == len(set(ids)) and len(cases.cases) >= 12
    units: set[tuple[str, str]] = set()
    for d in manifest.documents:
        segs = segment(d.doc_id, load_paragraphs(corpus_dir / d.text_path))
        for c in chunk_document(d, manifest, segs, lambda t: len(t.split())):
            if c.citation:
                units.add((d.act_id, c.citation))
                units.add((d.doc_id, c.citation))
            else:
                units.add((d.act_id, "notice"))
                units.add((d.doc_id, "notice"))
    for case in cases.cases:
        for ref in case.expected.must_cite + case.expected.may_also_cite:
            assert tuple(ref) in units, (case.id, ref)
            assert "@" in ref[0], (
                f"{case.id}: cite the document, version included, not the act alone: {ref[0]}"
            )
        if case.kind in ("refusal", "ambiguous"):
            assert case.expected.outcome == "refused" and not case.expected.must_cite, case.id
            assert case.kind != "refusal" or not case.expected.gap_mentions, (
                f"{case.id}: a question the corpus bears on belongs to partial, not refusal"
            )
        if case.kind == "partial":
            # A partial cites what the corpus covers; that the gap is declared at all is
            # enforced by the Draft model, so gap_mentions stays an optional sharpener —
            # partial-344's gap is epistemic and has no phrase worth demanding.
            assert case.expected.outcome == "partial" and case.expected.must_cite, case.id
        if case.kind == "revoked":
            assert any(ref[1] == "notice" for ref in case.expected.must_cite), (
                f"{case.id}: a revoked act is only ever cited with its revocation"
            )
            assert any(ref[1] != "notice" for ref in case.expected.must_cite), (
                f"{case.id}: and with the provision it answers from, or it answers nothing"
            )
        if case.kind == "version":
            assert any(ref[0].endswith("@v5") for ref in case.expected.must_cite), case.id


def chunk_ids(small_index, doc_id: str, unit: str | None):
    return [c for c in small_index.chunks if c.doc_id == doc_id and c.citation == unit]


def test_compare_checks_form_not_content(small_index):
    cases = {c.id: c for c in gen.load_cases().cases}
    v5 = chunk_ids(small_index, "circular-3978-2020@v5", "art. 70, caput")[0]
    v1 = chunk_ids(small_index, "circular-3978-2020@v1", "art. 70, caput")[0]
    good = Response(
        request_id="r",
        outcome=Outcome.ANSWERED,
        draft=Draft(
            outcome="answered",
            statements=(
                Statement(
                    text="Entra em vigor em 1º de outubro de 2020; o original previa julho.",
                    citations=(
                        Citation(doc_id=v5.doc_id, chunk_id=v5.chunk_id, locator="art. 70, caput"),
                        Citation(doc_id=v1.doc_id, chunk_id=v1.chunk_id, locator="art. 70, caput"),
                    ),
                ),
            ),
        ),
    )
    assert gen.compare(cases["version-70"], good, small_index).ok
    wrong_text = good.model_copy(
        update={
            "draft": good.draft.model_copy(
                update={
                    "statements": (
                        good.draft.statements[0].model_copy(update={"text": "Julho de 2020."}),
                    )
                }
            )
        }
    )
    assert gen.compare(cases["version-70"], wrong_text, small_index).mismatches == (
        "statements do not say '1º de outubro de 2020'",
    )
    refused = Response(
        request_id="r", outcome=Outcome.REFUSED, refusal_reason=RefusalReason.NOT_IN_CORPUS
    )
    mismatches = gen.compare(cases["version-70"], refused, small_index).mismatches
    assert mismatches[0].startswith("outcome refused, expected answered")
    assert gen.compare(cases["refusal-pena"], refused, small_index).ok
    ambiguous = Response(
        request_id="r", outcome=Outcome.REFUSED, refusal_reason=RefusalReason.AMBIGUOUS
    )
    assert gen.compare(cases["ambiguous-prazo"], ambiguous, small_index).ok
    assert not gen.compare(cases["ambiguous-prazo"], refused, small_index).ok

    notice = next(
        c for c in small_index.chunks if c.doc_id == "circular-3461-2009@v10" and c.kind == "notice"
    )
    art4 = chunk_ids(small_index, "circular-3461-2009@v10", "art. 4º, caput")[0]
    revoked = Response(
        request_id="r",
        outcome=Outcome.ANSWERED,
        draft=Draft(
            outcome="answered",
            statements=(
                Statement(
                    text="A 3.461 exigia...; foi revogada pela 3.978.",
                    citations=(
                        Citation(
                            doc_id=art4.doc_id, chunk_id=art4.chunk_id, locator="art. 4º, caput"
                        ),
                        Citation(
                            doc_id=notice.doc_id, chunk_id=notice.chunk_id, locator="revogação"
                        ),
                    ),
                ),
            ),
        ),
    )
    assert gen.compare(cases["revoked-pep"], revoked, small_index).ok
    gold_piece = next(
        c
        for c in small_index.chunks
        if c.doc_id == "carta-circular-4001-2020@v4" and c.citation == "art. 1º, caput"
    )
    partial = Response(
        request_id="r",
        outcome=Outcome.PARTIAL,
        draft=Draft(
            outcome="partial",
            statements=(
                Statement(
                    text="Indícios ligados ao ouro.",
                    citations=(
                        Citation(
                            doc_id=gold_piece.doc_id,
                            chunk_id=gold_piece.chunk_id,
                            locator="art. 1º, XIX",
                        ),
                    ),
                ),
            ),
            gaps=(Gap(text="procedimentos de compra", where="IN BCB 406/2023, fora deste corpus"),),
        ),
    )
    assert gen.compare(cases["partial-ouro"], partial, small_index).ok


class ScriptedLive:
    model = GENERATION_MODEL

    def __init__(self, text: str) -> None:
        self.text, self.calls = text, 0

    def complete(self, request) -> Completion:
        self.calls += 1
        return Completion(
            text=self.text, model=self.model, input_tokens=1200, output_tokens=60, live=True
        )


REFUSAL = json.dumps(
    {
        "outcome": "refused",
        "statements": [],
        "gaps": [],
        "refusal_reason": "not_in_corpus",
        "refusal_note": None,
    }
)


def make_gateway(
    manifest, corpus_dir, small_index, embedder, provider, trail: Path, ceiling=0.05
) -> Gateway:
    return Gateway(
        manifest=manifest,
        manifest_path=corpus_dir / "manifest.json",
        corpus_dir=corpus_dir,
        index=small_index,
        embedder=embedder,
        provider=provider,
        budget=Budget(ceiling),
        audit=AuditLog(trail),
        prompt=Prompt.load("answer-v1"),
    )


def test_recorder_refuses_unless_live(manifest, corpus_dir, small_index, embedder, tmp_path):
    gateway = make_gateway(
        manifest,
        corpus_dir,
        small_index,
        embedder,
        RecordedProvider(tmp_path / "c.jsonl"),
        tmp_path / "t.jsonl",
    )
    with pytest.raises(NotLive):
        record(gen.load_cases(), gateway, tmp_path / "out", 1.0, date(2026, 9, 14))
    assert not (tmp_path / "out").exists(), "nothing written"


def test_recorder_stops_on_the_run_level_cap_before_the_call(
    manifest, corpus_dir, small_index, embedder, tmp_path
):
    live = ScriptedLive(REFUSAL)
    provider = RecordingProvider(live, tmp_path / "c.jsonl", today=date(2026, 9, 14))
    gateway = make_gateway(
        manifest, corpus_dir, small_index, embedder, provider, tmp_path / "t.jsonl"
    )
    with pytest.raises(RuntimeError, match="would exceed --max-total-usd"):
        record(gen.load_cases(), gateway, tmp_path / "out", 0.0001, date(2026, 9, 14))
    assert live.calls == 0, "the cap stops before the first call"


def test_recorder_writes_responses_and_a_grades_template_it_never_overwrites(
    manifest, corpus_dir, small_index, embedder, tmp_path
):
    live = ScriptedLive(REFUSAL)
    provider = RecordingProvider(live, tmp_path / "c.jsonl", today=date(2026, 9, 14))
    gateway = make_gateway(
        manifest, corpus_dir, small_index, embedder, provider, tmp_path / "t.jsonl"
    )
    cases = gen.load_cases()
    two = cases.model_copy(update={"cases": cases.cases[:2]})
    done = record(two, gateway, tmp_path / "out", 5.0, date(2026, 9, 14))
    assert [d.case_id for d in done] == [c.id for c in two.cases] and live.calls == 2
    for c in two.cases:
        payload = json.loads(
            (tmp_path / "out" / "responses" / f"{c.id}.json").read_text(encoding="utf-8")
        )
        assert payload["response"]["outcome"] == "refused" and payload["audit_outcome"] == "refused"
    grades = gen.Grades.model_validate_json(
        (tmp_path / "out" / "grades.json").read_text(encoding="utf-8")
    )
    assert set(grades.grades) == {c.id for c in two.cases} and all(
        g.verdict is None for g in grades.grades.values()
    )
    (tmp_path / "out" / "grades.json").write_text(
        '{"graded_by": "k", "graded_on": "2026-09-15", "grades": {}}', encoding="utf-8"
    )
    record(two, gateway, tmp_path / "out", 5.0, date(2026, 9, 15))
    assert '"graded_by": "k"' in (tmp_path / "out" / "grades.json").read_text(encoding="utf-8"), (
        "grades are the author's"
    )


def test_gate_replays_recordings_and_holds_them_to_expectation_and_grade(
    manifest, corpus_dir, small_index, embedder, tmp_path
):
    cases = gen.load_cases()
    two = cases.model_copy(
        update={"cases": tuple(c for c in cases.cases if c.id in ("refusal-pena", "version-70"))}
    )
    live = ScriptedLive(REFUSAL)  # refuses everything: right for refusal-pena, wrong for version-70
    recorder = make_gateway(
        manifest,
        corpus_dir,
        small_index,
        embedder,
        RecordingProvider(live, tmp_path / "c.jsonl", today=date(2026, 9, 14)),
        tmp_path / "t1.jsonl",
    )
    record(two, recorder, tmp_path / "out", 5.0, date(2026, 9, 14))
    grades = gen.Grades(
        graded_by="author",
        graded_on=date(2026, 9, 15),
        grades={
            "refusal-pena": gen.Grade(verdict="pass"),
            "version-70": gen.Grade(verdict="fail", notes="refused the demonstration question"),
        },
    )
    (tmp_path / "out" / "grades.json").write_text(
        grades.model_dump_json(indent=2), encoding="utf-8"
    )

    replay = make_gateway(
        manifest,
        corpus_dir,
        small_index,
        embedder,
        RecordedProvider(tmp_path / "c.jsonl"),
        tmp_path / "t2.jsonl",
    )
    results = {r.case_id: r for r in gen.gate(two, replay, tmp_path / "out")}
    assert live.calls == 2, "the gate never went live"
    assert results["refusal-pena"].ok
    assert not results["version-70"].ok
    assert (
        results["version-70"]
        .comparison.mismatches[0]
        .startswith("outcome refused, expected answered")
    )
    assert results["version-70"].grade.notes == "refused the demonstration question"
    assert all(r.audit_outcome is Outcome.REFUSED for r in results.values())
