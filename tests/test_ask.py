"""The lock cycle end to end, with a fake provider: every path leaves exactly one audit
record, the budget's allowance reaches the provider, a blocked draft survives in the trail,
and a missing recording is recorded and raised — never answered live.

The index is built once for the two versions of Circular 3.978 (the demonstration case) and
Carta Circular 4.001 (the partial showcase).
"""

import json
import re
from datetime import date

import pytest

from eclusa.service.ask import REQUESTED_OUTPUT_TOKENS, Gateway
from eclusa.service.audit import AuditLog
from eclusa.service.budget import Budget, estimate_input_tokens
from eclusa.service.models import GENERATION_MODEL, cost_usd
from eclusa.service.outcomes import Outcome, RefusalReason
from eclusa.service.prompts import Prompt
from eclusa.service.provider import (
    Completion,
    CompletionRequest,
    RecordedProvider,
    RecordingMissing,
    RecordingProvider,
)

VERSION_QUESTION = "Quando a Circular 3.978 entra em vigor?"
GOLD_QUESTION = "Quais procedimentos devem ser adotados na compra de ouro?"


class ScriptedProvider:
    """Answers with whatever draft the test scripts, built from the request it receives."""

    model = GENERATION_MODEL

    def __init__(self, script) -> None:
        self.script = script  # request -> text
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest) -> Completion:
        self.requests.append(request)
        return Completion(
            text=self.script(request),
            model=self.model,
            input_tokens=1500,
            output_tokens=200,
            live=True,
        )


PASSAGE_HEADER = re.compile(
    r"^\[\d+\] doc_id=(?P<doc>\S+) chunk_id=(?P<chunk>\S+) locator=(?P<loc>.+?) \("
)


def passage_ids(request: CompletionRequest) -> dict[str, tuple[str, str]]:
    """chunk_id -> (doc_id, locator) as rendered in the user turn."""
    out = {}
    for line in request.input.splitlines():
        m = PASSAGE_HEADER.match(line)
        if m:
            out[m["chunk"]] = (m["doc"], m["loc"])
    return out


def draft_json(**fields) -> str:
    base = {
        "outcome": "refused",
        "statements": [],
        "gaps": [],
        "refusal_reason": None,
        "refusal_note": None,
    }
    base.update(fields)
    return json.dumps(base, ensure_ascii=False)


@pytest.fixture
def gateway_factory(manifest, corpus_dir, embedder, small_index, tmp_path):
    def make(provider, ceiling_usd: float = 0.05) -> Gateway:
        return Gateway(
            manifest=manifest,
            manifest_path=corpus_dir / "manifest.json",
            corpus_dir=corpus_dir,
            index=small_index,
            embedder=embedder,
            provider=provider,
            budget=Budget(ceiling_usd),
            audit=AuditLog(tmp_path / "audit.jsonl"),
            prompt=Prompt.load("answer-v1"),
        )

    return make


def only_record(gateway: Gateway):
    records = gateway.audit.records()
    assert len(records) == 1, "exactly one audit record per call"
    return records[0]


# --- the happy paths ---------------------------------------------------------------------------


def test_answered_with_both_versions_cited_is_delivered_and_recorded(gateway_factory):
    def script(request):
        ids = passage_ids(request)
        v5 = next(c for c, (d, loc) in ids.items() if d.endswith("@v5") and loc == "art. 70, caput")
        v1 = next(c for c, (d, loc) in ids.items() if d.endswith("@v1") and loc == "art. 70, caput")
        return draft_json(
            outcome="answered",
            statements=[
                {
                    "text": "Entra em vigor em 1º/10/2020; o texto original previa 1º de julho.",
                    "citations": [
                        {
                            "doc_id": "circular-3978-2020@v5",
                            "chunk_id": v5,
                            "locator": "art. 70, caput",
                        },
                        {
                            "doc_id": "circular-3978-2020@v1",
                            "chunk_id": v1,
                            "locator": "art. 70, caput",
                        },
                    ],
                }
            ],
        )

    provider = ScriptedProvider(script)
    gateway = gateway_factory(provider)
    response = gateway.ask(VERSION_QUESTION, request_id="req-answered")
    assert response.outcome is Outcome.ANSWERED
    assert response.draft.statements[0].citations[0].doc_id == "circular-3978-2020@v5"

    record = only_record(gateway)
    assert record.request_id == "req-answered" and record.outcome is Outcome.ANSWERED
    assert record.prompt_version == "answer-v1" and record.model == GENERATION_MODEL
    assert record.retrieval_k == 8 and len(record.retrieved_chunk_ids) == 8
    assert len(record.cited_chunk_ids) == 2
    assert record.cost_usd == pytest.approx(cost_usd(GENERATION_MODEL, 1500, 200))
    assert record.blocked_draft is None and record.violations == ()
    assert record.recorded_response is False, "a scripted provider is a live-shaped provider"


def test_partial_is_delivered_with_its_declared_gap(gateway_factory):
    def script(request):
        ids = passage_ids(request)
        chunk = next(c for c, (d, _) in ids.items() if d == "carta-circular-4001-2020@v4")
        return draft_json(
            outcome="partial",
            statements=[
                {
                    "text": "O corpus lista indícios ligados ao mercado de ouro.",
                    "citations": [
                        {
                            "doc_id": "carta-circular-4001-2020@v4",
                            "chunk_id": chunk,
                            "locator": "art. 1º, XIX",
                        }
                    ],
                }
            ],
            gaps=[
                {
                    "text": "procedimentos para a compra de ouro",
                    "where": "IN BCB 406/2023, fora deste corpus",
                }
            ],
        )

    gateway = gateway_factory(ScriptedProvider(script))
    response = gateway.ask(GOLD_QUESTION)
    assert (
        response.outcome is Outcome.PARTIAL
        or response.refusal_reason is RefusalReason.CONTRACT_VIOLATION
    )
    record = only_record(gateway)
    if response.outcome is Outcome.PARTIAL:
        assert record.outcome is Outcome.PARTIAL
        assert response.draft.gaps[0].where.endswith("fora deste corpus")
    else:  # inciso XIX was not in the retrieved piece: the contract caught the wrong locator
        assert record.outcome is Outcome.CONTRACT_VIOLATION and record.blocked_draft is not None


# --- the gate: what does not cross is still written down ---------------------------------------


def test_a_violating_draft_is_blocked_and_kept_whole_in_the_trail(gateway_factory):
    def script(request):
        ids = passage_ids(request)
        v1 = next(c for c, (d, loc) in ids.items() if d.endswith("@v1") and loc == "art. 70, caput")
        return draft_json(
            outcome="answered",
            statements=[
                {
                    "text": "Esta Circular entra em vigor em 1º de julho de 2020.",
                    "citations": [
                        {
                            "doc_id": "circular-3978-2020@v1",
                            "chunk_id": v1,
                            "locator": "art. 70, caput",
                        }
                    ],
                }
            ],
        )

    gateway = gateway_factory(ScriptedProvider(script))
    response = gateway.ask(VERSION_QUESTION)
    assert response.outcome is Outcome.REFUSED
    assert response.refusal_reason is RefusalReason.CONTRACT_VIOLATION
    assert response.draft is None, "julho never reaches the caller"

    record = only_record(gateway)
    assert record.outcome is Outcome.CONTRACT_VIOLATION
    assert record.violations and record.violations[0].startswith("superseded_without_current")
    assert record.blocked_draft is not None, "what the model tried to say is the evidence"
    assert "1º de julho de 2020" in record.blocked_draft.statements[0].text
    assert record.blocked_output_sha256 is not None and record.cited_chunk_ids == ()


def test_unparseable_output_is_a_contract_violation_with_the_raw_output_kept(gateway_factory):
    gateway = gateway_factory(ScriptedProvider(lambda request: "Não sei responder em JSON."))
    response = gateway.ask(VERSION_QUESTION)
    assert response.refusal_reason is RefusalReason.CONTRACT_VIOLATION
    record = only_record(gateway)
    assert record.outcome is Outcome.CONTRACT_VIOLATION
    assert record.blocked_output == "Não sei responder em JSON."
    assert record.violations == ("unparseable: the output is not a draft",)


def test_a_refusal_from_the_model_passes_through(gateway_factory):
    gateway = gateway_factory(
        ScriptedProvider(
            lambda r: draft_json(refusal_reason="not_in_corpus", refusal_note="nada sobre isso")
        )
    )
    response = gateway.ask("Qual a pena para o crime de lavagem de dinheiro?")
    assert (
        response.outcome is Outcome.REFUSED
        and response.refusal_reason is RefusalReason.NOT_IN_CORPUS
    )
    assert only_record(gateway).outcome is Outcome.REFUSED


# --- the budget is a stop, and its allowance reaches the provider ------------------------------


def test_budget_stops_before_the_provider_is_called(gateway_factory):
    provider = ScriptedProvider(lambda r: draft_json())
    gateway = gateway_factory(provider, ceiling_usd=0.0001)
    response = gateway.ask(VERSION_QUESTION)
    assert (
        response.outcome is Outcome.REFUSED
        and response.refusal_reason is RefusalReason.BUDGET_EXCEEDED
    )
    assert provider.requests == [], "no token was bought"
    record = only_record(gateway)
    assert record.outcome is Outcome.BUDGET_EXCEEDED and record.cost_usd == 0.0


def test_the_output_allowance_derived_from_the_budget_reaches_the_provider(gateway_factory):
    provider = ScriptedProvider(lambda r: draft_json(refusal_reason="not_in_corpus"))
    tight = gateway_factory(provider, ceiling_usd=0.005)
    tight.ask(VERSION_QUESTION)
    (request,) = provider.requests
    assert request.max_output_tokens < REQUESTED_OUTPUT_TOKENS, "the ceiling cut the request"
    estimate = estimate_input_tokens(request.instructions, request.input)
    worst = cost_usd(GENERATION_MODEL, estimate, request.max_output_tokens)
    assert worst <= 0.005 + 1e-9, "worst case bounded by the ceiling"
    assert request.json_schema is not None and request.temperature == 0.0
    assert set(request.context_ids) == set(passage_ids(request))


# --- recorded by default, never live by accident ----------------------------------------------


def test_a_missing_recording_is_recorded_as_provider_error_and_raised(gateway_factory, tmp_path):
    gateway = gateway_factory(RecordedProvider(tmp_path / "empty.jsonl"))
    with pytest.raises(RecordingMissing):
        gateway.ask(VERSION_QUESTION)
    record = only_record(gateway)
    assert (
        record.outcome is Outcome.PROVIDER_ERROR
        and record.refusal_reason is RefusalReason.PROVIDER_ERROR
    )


def test_a_recording_replays_and_the_trail_says_so(gateway_factory, tmp_path):
    cassette = tmp_path / "cassette.jsonl"
    scripted = ScriptedProvider(
        lambda r: draft_json(refusal_reason="ambiguous", refusal_note="qual circular?")
    )
    recorder = gateway_factory(RecordingProvider(scripted, cassette, today=date(2026, 9, 14)))
    first = recorder.ask("Qual o prazo?", request_id="rec")
    assert first.refusal_reason is RefusalReason.AMBIGUOUS

    replay = gateway_factory(RecordedProvider(cassette))
    second = replay.ask("Qual o prazo?", request_id="replay")
    assert second.refusal_note == "qual circular?"
    assert len(scripted.requests) == 1, "the replay never reached the scripted provider"
    record = replay.audit.records()[-1]
    assert record.recorded_response is True and record.recording_date == "2026-09-14"
    assert record.request_id == "replay"


def test_the_same_question_retrieves_the_same_context(gateway_factory):
    provider = ScriptedProvider(lambda r: draft_json(refusal_reason="not_in_corpus"))
    gateway = gateway_factory(provider)
    gateway.ask(VERSION_QUESTION)
    gateway.ask(VERSION_QUESTION)
    a, b = provider.requests
    assert a.context_ids == b.context_ids and a.key() == b.key()
    assert len(gateway.audit.records()) == 2


def test_prompts_live_on_disk_and_are_versioned(tmp_path):
    prompt = Prompt.load("answer-v1")
    assert "partial" in prompt.system and "{question}" in prompt.user_template
    with pytest.raises(ValueError, match="answer-v1"):
        Prompt.load("answer")
    with pytest.raises(FileNotFoundError):
        Prompt.load("answer-v99")
