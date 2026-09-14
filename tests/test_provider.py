"""The provider: recorded by default, live only on purpose, and the suite cannot spend money."""

import sys
from datetime import date
from pathlib import Path

import pytest

from eclusa.service.audit import AuditLog, AuditRecord
from eclusa.service.budget import Budget, BudgetExceeded, estimate_input_tokens
from eclusa.service.models import DATED, GENERATION_MODEL, PRICES, cost_usd
from eclusa.service.outcomes import Outcome
from eclusa.service.provider import (
    Completion,
    CompletionRequest,
    OpenAIProvider,
    RecordedProvider,
    RecordingMissing,
    RecordingProvider,
    provider_from_env,
)


def request(**overrides) -> CompletionRequest:
    base = dict(
        model=GENERATION_MODEL,
        prompt_version="answer-v1",
        instructions="Responda só com o corpus.",
        input="Pergunta: quando entra em vigor?\n[1] Art. 70. ...",
        context_ids=("circular-3978-2020@v5#0444",),
        max_output_tokens=400,
    )
    base.update(overrides)
    return CompletionRequest(**base)


class FakeLive:
    model = GENERATION_MODEL

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, req: CompletionRequest) -> Completion:
        self.calls += 1
        return Completion(
            text='{"outcome":"refused"}',
            model=req.model,
            input_tokens=120,
            output_tokens=8,
            live=True,
        )


# --- the default cannot spend money -----------------------------------------------------------


def test_default_provider_is_recorded_and_the_sdk_is_never_imported(tmp_path: Path):
    for name in [m for m in sys.modules if m == "openai" or m.startswith("openai.")]:
        del sys.modules[name]
    p = provider_from_env(tmp_path / "cassette.jsonl", environ={})
    assert isinstance(p, RecordedProvider)
    assert "openai" not in sys.modules, "recorded mode must not even load the live SDK"
    also = provider_from_env(tmp_path / "c.jsonl", environ={"OPENAI_API_KEY": "sk-test"})
    assert isinstance(also, RecordedProvider), "a key alone does not make the run live"


def test_a_missing_recording_fails_loud_and_never_goes_live(tmp_path: Path):
    p = RecordedProvider(tmp_path / "cassette.jsonl")
    with pytest.raises(RecordingMissing, match="never calls the model"):
        p.complete(request())


def test_live_requires_the_flag_and_the_key_together(tmp_path: Path):
    with pytest.raises(RuntimeError, match="refusing to guess"):
        provider_from_env(tmp_path / "c.jsonl", environ={"ECLUSA_LIVE": "1"})


# --- recordings: keyed on context, dated, replayed --------------------------------------------


def test_recording_then_replay_round_trips_model_and_date(tmp_path: Path):
    cassette = tmp_path / "cassette.jsonl"
    live = FakeLive()
    recorder = RecordingProvider(live, cassette, today=date(2026, 9, 14))
    first = recorder.complete(request())
    assert first.live and live.calls == 1

    replay = RecordedProvider(cassette)
    assert len(replay) == 1
    again = replay.complete(request())
    assert again.text == first.text and again.model == GENERATION_MODEL
    assert again.recorded_at == date(2026, 9, 14) and not again.live
    assert replay.recorded_dates() == [date(2026, 9, 14)]
    assert live.calls == 1, "replay did not touch the live provider"


def test_the_key_includes_the_retrieved_context_not_only_the_prompt():
    a = request()
    same_prompt_other_context = request(context_ids=("circular-3978-2020@v1#0440",))
    assert a.key() != same_prompt_other_context.key(), (
        "a change in retrieval must not reuse a recording"
    )
    assert a.key() != request(input=a.input + " ").key()
    assert a.key() != request(prompt_version="answer-v2").key()
    assert a.key() != request(model="gpt-5-mini-2025-08-07").key()
    assert a.key() == request().key(), "and it is stable"


def test_a_recording_for_another_context_is_a_miss(tmp_path: Path):
    cassette = tmp_path / "cassette.jsonl"
    RecordingProvider(FakeLive(), cassette, today=date(2026, 9, 14)).complete(request())
    with pytest.raises(RecordingMissing):
        RecordedProvider(cassette).complete(request(context_ids=("other#0001",)))


def test_the_live_provider_shapes_the_request_as_the_responses_api_expects():
    class FakeResponses:
        def __init__(self) -> None:
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs

            class Usage:
                input_tokens, output_tokens = 100, 20

            class R:
                output_text = '{"outcome":"refused","refusal_reason":"not_in_corpus"}'
                model = GENERATION_MODEL
                usage = Usage()

            return R()

    class FakeClient:
        responses = FakeResponses()

    client = FakeClient()
    p = OpenAIProvider(client=client)
    completion = p.complete(request(json_schema={"type": "object"}))
    sent = client.responses.kwargs
    assert sent["model"] == GENERATION_MODEL and sent["store"] is False
    assert sent["max_output_tokens"] == 400 and sent["temperature"] == 0.0
    assert (
        sent["text"]["format"]["type"] == "json_schema" and sent["text"]["format"]["strict"] is True
    )
    assert completion.live and (completion.input_tokens, completion.output_tokens) == (100, 20)


# --- the model is dated and priced; the budget stops before the call ---------------------------


def test_generation_model_is_a_dated_snapshot_with_a_known_price():
    assert DATED.search(GENERATION_MODEL), "an alias moves without notice"
    assert GENERATION_MODEL in PRICES
    assert all(DATED.search(m) for m in PRICES)
    # gpt-5.4-mini: US$ 0.75 / 4.50 per million, pricing page read on 2026-09-14
    assert cost_usd("gpt-5.4-mini-2026-03-17", 1_000_000, 1_000_000) == pytest.approx(5.25)
    with pytest.raises(KeyError):
        cost_usd("gpt-unknown-2099-01-01", 1, 1)


def test_the_budget_derives_the_output_allowance_and_bounds_the_worst_case():
    tokens = estimate_input_tokens("x" * 2500)  # ~1000 tokens, estimated high on purpose
    assert tokens >= 1000
    # gpt-5.4-mini: 1000 input tokens cost US$ 0.00075; a ceiling of US$ 0.002 leaves
    # US$ 0.00125, which buys 277 output tokens at US$ 4.50 per million.
    allowance = Budget(ceiling_usd=0.002).allowance(GENERATION_MODEL, tokens, requested_output=900)
    assert allowance.max_output_tokens < 900, "the request asked for more than the ceiling buys"
    assert allowance.max_output_tokens == int((0.002 - tokens * 0.75 / 1e6) * 1e6 / 4.50)
    assert allowance.worst_case_usd <= 0.002, "input estimate plus every allowed output token"
    generous = Budget(ceiling_usd=1.0).allowance(GENERATION_MODEL, tokens, requested_output=900)
    assert generous.max_output_tokens == 900, "capped by the request when the ceiling allows"


def test_the_budget_stops_before_the_call_when_nothing_useful_fits():
    tokens = estimate_input_tokens("x" * 2500)
    with pytest.raises(BudgetExceeded, match="input alone"):
        Budget(ceiling_usd=0.0005).allowance(GENERATION_MODEL, tokens, requested_output=900)
    with pytest.raises(BudgetExceeded, match="fewer than the 64"):
        Budget(ceiling_usd=0.00090).allowance(GENERATION_MODEL, tokens, requested_output=900)


# --- the audit trail is appended, never rewritten ---------------------------------------------


def test_audit_records_are_appended_one_per_call_including_failures(tmp_path: Path):
    log = AuditLog(tmp_path / "audit" / "trail.jsonl")

    def rec(i: int, outcome: Outcome, **extra) -> AuditRecord:
        return AuditRecord(
            request_id=f"req-{i}",
            question_sha256="0" * 64,
            prompt_version="answer-v1",
            model=GENERATION_MODEL,
            corpus_manifest_sha256="1" * 64,
            index_model_revision="614241f6",
            retrieval_k=8,
            retrieved_chunk_ids=("a#0001",),
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            outcome=outcome,
            recorded_response=True,
            latency_ms=3,
            **extra,
        )

    log.append(rec(1, Outcome.ANSWERED, cited_chunk_ids=("a#0001",)))
    log.append(rec(2, Outcome.BUDGET_EXCEEDED, refusal_reason="budget_exceeded"))
    log.append(rec(3, Outcome.CONTRACT_VIOLATION, violations=("superseded_without_current: ...",)))
    log.append(rec(4, Outcome.PARTIAL))
    records = log.records()
    assert [r.outcome for r in records] == [
        Outcome.ANSWERED,
        Outcome.BUDGET_EXCEEDED,
        Outcome.CONTRACT_VIOLATION,
        Outcome.PARTIAL,
    ]
    lines = (tmp_path / "audit" / "trail.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    log.append(rec(5, Outcome.REFUSED, refusal_reason="not_in_corpus"))
    assert (tmp_path / "audit" / "trail.jsonl").read_text(encoding="utf-8").splitlines()[
        :4
    ] == lines
