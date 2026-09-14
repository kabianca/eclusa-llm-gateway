"""The lock cycle: a question enters, and what leaves has been checked, charged and written down.

    retrieve -> budget (hard stop) -> provider (recorded by default) -> contract -> audit

Every path through this function writes exactly one audit record — answered,
partial, refused, stopped by the budget, blocked by the contract, or failed at
the provider — and the failure paths are exercised by tests, not just described.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from eclusa.corpus.manifest import Manifest
from eclusa.index.embedding import Embedder
from eclusa.index.store import IndexStore
from eclusa.ingest.extract import load_paragraphs
from eclusa.ingest.segment import Segment, segment
from eclusa.service.audit import AuditLog, AuditRecord
from eclusa.service.budget import Budget, BudgetExceeded, estimate_input_tokens
from eclusa.service.contract import Draft, Response, Retrieved, draft_json_schema, enforce
from eclusa.service.models import GENERATION_MODEL, cost_usd
from eclusa.service.outcomes import Outcome, RefusalReason
from eclusa.service.prompts import Prompt
from eclusa.service.provider import Completion, CompletionRequest, Provider

REQUESTED_OUTPUT_TOKENS = (
    900  # what a full partial answer with citations needs; the budget may cut it
)


@dataclass
class Gateway:
    manifest: Manifest
    manifest_path: Path
    corpus_dir: Path
    index: IndexStore
    embedder: Embedder
    provider: Provider
    budget: Budget
    audit: AuditLog
    prompt: Prompt
    model: str = GENERATION_MODEL
    k: int = 8
    _segments: dict[str, list[Segment]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        for doc in self.manifest.documents:
            paragraphs = load_paragraphs(self.corpus_dir / doc.text_path)
            self._segments[doc.doc_id] = segment(doc.doc_id, paragraphs)
        self._manifest_sha = hashlib.sha256(self.manifest_path.read_bytes()).hexdigest()

    def ask(self, question: str, request_id: str | None = None) -> Response:
        request_id = request_id or uuid.uuid4().hex
        started = time.monotonic()
        hits = self.index.search(self.embedder.embed_query(question), k=self.k)
        chunks = [h.chunk for h in hits]
        retrieved = Retrieved(chunks=tuple(chunks), segments=self._segments)
        base = dict(
            request_id=request_id,
            question_sha256=hashlib.sha256(question.encode("utf-8")).hexdigest(),
            prompt_version=self.prompt.version,
            model=self.model,
            corpus_manifest_sha256=self._manifest_sha,
            index_model_revision=self.index.meta["model_revision"],
            retrieval_k=self.k,
            retrieved_chunk_ids=tuple(c.chunk_id for c in chunks),
        )

        instructions = self.prompt.system
        user = self.prompt.render_user(question, chunks, self.manifest)
        try:
            allowance = self.budget.allowance(
                self.model, estimate_input_tokens(instructions, user), REQUESTED_OUTPUT_TOKENS
            )
        except BudgetExceeded as exc:
            self._record(base, started, Outcome.BUDGET_EXCEEDED, RefusalReason.BUDGET_EXCEEDED)
            return Response(
                request_id=request_id,
                outcome=Outcome.REFUSED,
                refusal_reason=RefusalReason.BUDGET_EXCEEDED,
                refusal_note=str(exc),
            )

        request = CompletionRequest(
            model=self.model,
            prompt_version=self.prompt.version,
            instructions=instructions,
            input=user,
            context_ids=tuple(c.chunk_id for c in chunks),
            max_output_tokens=allowance.max_output_tokens,
            json_schema=draft_json_schema(),
        )
        try:
            completion = self.provider.complete(request)
        except Exception:
            self._record(base, started, Outcome.PROVIDER_ERROR, RefusalReason.PROVIDER_ERROR)
            raise

        usage = dict(
            model=completion.model,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            cost_usd=cost_usd(self.model, completion.input_tokens, completion.output_tokens),
            recorded_response=not completion.live,
            recording_date=completion.recorded_at.isoformat() if completion.recorded_at else None,
        )
        draft = _parse(completion)
        if draft is None:
            self._record(
                base,
                started,
                Outcome.CONTRACT_VIOLATION,
                RefusalReason.CONTRACT_VIOLATION,
                violations=("unparseable: the output is not a draft",),
                blocked_output_sha256=_sha(completion.text),
                blocked_output=completion.text,
                **usage,
            )
            return Response(
                request_id=request_id,
                outcome=Outcome.REFUSED,
                refusal_reason=RefusalReason.CONTRACT_VIOLATION,
                refusal_note="the model's output could not be read as a draft",
            )

        enforced = enforce(request_id, draft, retrieved, self.manifest)
        cited = tuple(c.chunk_id for s in draft.statements for c in s.citations)
        self._record(
            base,
            started,
            enforced.outcome,
            enforced.response.refusal_reason,
            cited_chunk_ids=cited if enforced.blocked is None else (),
            violations=tuple(f"{v.rule}: {v.detail}" for v in enforced.violations),
            blocked_draft=enforced.blocked,
            blocked_output_sha256=_sha(completion.text) if enforced.blocked else None,
            **usage,
        )
        return enforced.response

    def _record(
        self,
        base: dict,
        started: float,
        outcome: Outcome,
        refusal_reason: RefusalReason | None,
        **extra,
    ) -> None:
        defaults = dict(
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            recorded_response=True,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        self.audit.append(
            AuditRecord(
                **{
                    **base,
                    **defaults,
                    **extra,
                    "outcome": outcome,
                    "refusal_reason": refusal_reason,
                }
            )
        )


def _parse(completion: Completion) -> Draft | None:
    try:
        return Draft.model_validate(json.loads(completion.text))
    except (json.JSONDecodeError, ValidationError):
        return None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
