"""The HTTP service: the lock, behind four endpoints.

``/readyz`` is the one that matters. It returns 200 only after the frozen corpus
is loaded, the index is on disk and read, and the embedding model is in memory —
the three things that take time and the three things whose absence would make an
answer impossible. A readiness probe that answers before that is the ``/ping``
the Kubernetes part of this project exists to avoid: the pod would be sent
traffic it cannot serve, and the first user would get the error instead of the
rollout.

The service starts, becomes ready and answers **with no network and no API key**:
the provider replays recordings unless ``ECLUSA_LIVE=1`` and a key are both set.
That is what lets a cluster smoke test ask a real question and assert a real
answer without a card, and it is the same property the test suite relies on.
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from eclusa.corpus import manifest as manifest_mod
from eclusa.index.embedding import Embedder
from eclusa.index.store import IndexStore
from eclusa.service.ask import Gateway
from eclusa.service.audit import AuditLog
from eclusa.service.budget import Budget
from eclusa.service.contract import Response as LockResponse
from eclusa.service.models import GENERATION_MODEL
from eclusa.service.outcomes import Outcome
from eclusa.service.prompts import Prompt
from eclusa.service.provider import provider_from_env

CORPUS_DIR = Path(os.environ.get("ECLUSA_CORPUS", "corpus"))
INDEX_DIR = Path(os.environ.get("ECLUSA_INDEX", "var/index"))
CASSETTE = Path(os.environ.get("ECLUSA_CASSETTE", "eval/generation/recordings.jsonl"))
AUDIT_PATH = Path(os.environ.get("ECLUSA_AUDIT", "var/audit/trail.jsonl"))
CEILING_USD = float(os.environ.get("ECLUSA_CEILING_USD", "0.02"))
PROMPT_VERSION = os.environ.get("ECLUSA_PROMPT", "answer-v1")


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


@dataclass
class State:
    gateway: Gateway | None = None
    ready_at: datetime | None = None
    started: float = field(default_factory=time.monotonic)
    counts: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0

    @property
    def ready(self) -> bool:
        return self.gateway is not None


state = State()


def build_gateway() -> Gateway:
    """Everything slow happens here: the corpus, the index and the model."""
    manifest_path = CORPUS_DIR / "manifest.json"
    return Gateway(
        manifest=manifest_mod.load(manifest_path),
        manifest_path=manifest_path,
        corpus_dir=CORPUS_DIR,
        index=IndexStore.load(INDEX_DIR),
        embedder=Embedder.pinned(),
        provider=provider_from_env(CASSETTE),
        budget=Budget(CEILING_USD),
        audit=AuditLog(AUDIT_PATH),
        prompt=Prompt.load(PROMPT_VERSION),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.gateway = build_gateway()
    state.ready_at = datetime.now(UTC)
    yield
    state.gateway = None


app = FastAPI(title="Eclusa", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict:
    """The process is alive. It says nothing about being able to answer."""
    return {"status": "ok", "uptime_s": round(time.monotonic() - state.started, 1)}


@app.get("/readyz")
def readyz():
    """Ready means the corpus is loaded, the index is read and the model is in memory."""
    if not state.ready:
        raise HTTPException(status_code=503, detail="loading the corpus, the index and the model")
    gateway = state.gateway
    return {
        "status": "ready",
        "since": state.ready_at.isoformat(),
        "documents": len(gateway.manifest.documents),
        "chunks": len(gateway.index.chunks),
        "model": gateway.model,
        "embedding_revision": gateway.index.meta["model_revision"],
        "chunk_policy": gateway.index.meta["chunk_policy"],
        "live": gateway.provider.__class__.__name__ != "RecordedProvider",
    }


@app.post("/ask", response_model=LockResponse)
def ask(body: Question) -> LockResponse:
    if not state.ready:
        raise HTTPException(status_code=503, detail="not ready")
    response = state.gateway.ask(body.question)
    record = state.gateway.audit.records()[-1]
    state.counts[record.outcome.value] = state.counts.get(record.outcome.value, 0) + 1
    state.cost_usd += record.cost_usd
    return response


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    """Prometheus text format, by hand: four numbers worth watching and no new dependency."""
    lines = [
        "# HELP eclusa_ready 1 when the corpus, the index and the model are loaded.",
        "# TYPE eclusa_ready gauge",
        f"eclusa_ready {int(state.ready)}",
        "# HELP eclusa_requests_total Requests by what the audit trail recorded.",
        "# TYPE eclusa_requests_total counter",
    ]
    for outcome in Outcome:
        n = state.counts.get(outcome.value, 0)
        lines.append(f'eclusa_requests_total{{outcome="{outcome.value}"}} {n}')
    lines += [
        "# HELP eclusa_cost_usd_total What the generation model has cost this process.",
        "# TYPE eclusa_cost_usd_total counter",
        f"eclusa_cost_usd_total {state.cost_usd:.6f}",
        "# HELP eclusa_model_info The pinned generation model, as every audit record carries it.",
        "# TYPE eclusa_model_info gauge",
        f'eclusa_model_info{{model="{GENERATION_MODEL}"}} 1',
    ]
    return "\n".join(lines) + "\n"
