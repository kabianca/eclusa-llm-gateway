"""The service: ready only when it can actually answer, and answering with no network.

The readiness test is the one that carries the Kubernetes argument. A probe that
answers 200 while the index is still loading would have the pod receive traffic it
cannot serve, which is the `/ping` the manifests exist to avoid.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eclusa.service import app as app_mod
from eclusa.service.models import GENERATION_MODEL


@pytest.fixture
def service(manifest, corpus_dir, small_index, embedder, tmp_path, monkeypatch):
    """The real gateway over the small index, with the provider that replays recordings."""
    from eclusa.service.ask import Gateway
    from eclusa.service.audit import AuditLog
    from eclusa.service.budget import Budget
    from eclusa.service.prompts import Prompt
    from eclusa.service.provider import RecordedProvider

    cassette = Path("eval/generation/recordings.jsonl")
    monkeypatch.setattr(
        app_mod,
        "build_gateway",
        lambda: Gateway(
            manifest=manifest,
            manifest_path=corpus_dir / "manifest.json",
            corpus_dir=corpus_dir,
            index=small_index,
            embedder=embedder,
            provider=RecordedProvider(cassette),
            budget=Budget(0.05),
            audit=AuditLog(tmp_path / "trail.jsonl"),
            prompt=Prompt.load("answer-v1"),
        ),
    )
    app_mod.state.counts = {}
    app_mod.state.cost_usd = 0.0
    with TestClient(app_mod.app) as client:
        yield client


def test_not_ready_before_the_corpus_and_the_index_are_loaded(monkeypatch):
    # Outside the lifespan nothing is loaded: readyz must say so with 503, and /ask refuse.
    app_mod.state.gateway = None
    client = TestClient(app_mod.app)  # no "with": lifespan does not run
    assert client.get("/healthz").status_code == 200, "alive is not the same as able to answer"
    assert client.get("/readyz").status_code == 503
    assert client.post("/ask", json={"question": "Qualquer pergunta?"}).status_code == 503
    assert "eclusa_ready 0" in client.get("/metrics").text


def test_ready_says_what_it_loaded(service):
    body = service.get("/readyz").json()
    assert body["status"] == "ready"
    assert body["documents"] == 21 and body["chunks"] > 0
    assert body["model"] == GENERATION_MODEL
    assert body["chunk_policy"] == "units-v2"
    assert body["live"] is False, "the pod answers from recordings: no network, no key"


def test_healthz_is_alive_not_ready(service):
    assert service.get("/healthz").json()["status"] == "ok"


def test_metrics_counts_what_the_audit_trail_recorded(service):
    before = service.get("/metrics").text
    assert "eclusa_ready 1" in before
    assert f'eclusa_model_info{{model="{GENERATION_MODEL}"}} 1' in before
    assert 'eclusa_requests_total{outcome="answered"} 0' in before


@pytest.mark.slow
def test_the_pod_answers_a_recorded_question_with_no_network(
    manifest, corpus_dir, full_index, embedder, tmp_path, monkeypatch
):
    """What the cluster smoke test asserts, asserted here first.

    The question is one of the recorded evaluation cases, word for word, so the whole lock
    runs — retrieval over the real index, the budget, the replayed provider, the contract,
    the audit trail — and the answer comes back cited, with nothing reaching the network.
    """
    from eclusa.service.ask import Gateway
    from eclusa.service.audit import AuditLog
    from eclusa.service.budget import Budget
    from eclusa.service.prompts import Prompt
    from eclusa.service.provider import RecordedProvider

    monkeypatch.setattr(
        app_mod,
        "build_gateway",
        lambda: Gateway(
            manifest=manifest,
            manifest_path=corpus_dir / "manifest.json",
            corpus_dir=corpus_dir,
            index=full_index,
            embedder=embedder,
            provider=RecordedProvider(Path("eval/generation/recordings.jsonl")),
            budget=Budget(0.05),
            audit=AuditLog(tmp_path / "trail.jsonl"),
            prompt=Prompt.load("answer-v1"),
        ),
    )
    app_mod.state.counts = {}
    app_mod.state.cost_usd = 0.0
    with TestClient(app_mod.app) as client:
        question = "Qual é o objetivo da avaliação interna de risco prevista na Circular 3.978?"
        body = client.post("/ask", json={"question": question}).json()
        assert body["outcome"] == "answered"
        statement = body["draft"]["statements"][0]
        assert statement["citations"][0]["locator"] == "art. 10, caput"
        assert "identificar e mensurar o risco" in statement["text"]
        assert 'eclusa_requests_total{outcome="answered"} 1' in client.get("/metrics").text
