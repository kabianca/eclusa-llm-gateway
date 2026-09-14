"""One record per call, appended, never mutated. The trail is the product.

Every request — answered, partial, refused, stopped by the budget, or caught by
the contract — leaves exactly one record with what it cost and what happened.
A draft the contract blocked is kept whole in its record: "the model tried to
say X and was stopped" is the evidence that the gate worked, and *nothing
crosses unrecorded* includes what did not cross.
The file is opened in append mode and nothing here can rewrite a line; a reader
exists so that tests and the drift monitor can look at the trail, not because
anything edits it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from eclusa.service.contract import Draft
from eclusa.service.outcomes import Outcome, RefusalReason


class AuditRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    question_sha256: str  # the question itself stays out of the trail; its hash ties it back
    prompt_version: str
    model: str  # the pinned identifier, and after a live call the one the provider reported
    corpus_manifest_sha256: str
    index_model_revision: str
    retrieval_k: int  # moves the input tokens and therefore the cost; the trail must explain it
    retrieved_chunk_ids: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    outcome: Outcome
    refusal_reason: RefusalReason | None = None
    cited_chunk_ids: tuple[str, ...] = ()
    violations: tuple[str, ...] = ()
    blocked_draft: Draft | None = None  # what the model tried to say and the contract stopped
    blocked_output_sha256: str | None = None  # of the raw model output, parseable or not
    blocked_output: str | None = None  # the raw output when it could not even be parsed
    recorded_response: bool  # replayed from the cassette (True) or a live call (False)
    recording_date: str | None = None
    latency_ms: int


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def append(self, record: AuditRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(record.model_dump_json() + "\n")

    def records(self) -> list[AuditRecord]:
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as fh:
            return [AuditRecord.model_validate_json(line) for line in fh if line.strip()]
