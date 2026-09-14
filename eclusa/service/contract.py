"""The output contract: citation required, or refuse.

Two models live here. ``Draft`` is what the language model has to produce — the
JSON shape it is asked for — and ``verify`` is what makes it an answer or not:
every citation must name a document in the frozen corpus, a chunk that was
retrieved *for this request*, and a locator that exists inside that chunk. A
citation that fails any of the three is a contract violation, and a draft with a
violation never reaches the caller.

Two rules go beyond "the citation resolves", because resolving is not enough
when the text moves. A statement that cites a superseded version of an act must
also cite the version in force — the original is history, never the answer. And
a statement whose only support is a revoked act must cite that act's revocation
notice — a question about Circular 3.461 is answered with the revocation stated,
never silently from the superseded text.

``Response`` is what leaves the lock: the outcome, the verified draft or the
refusal, and the request id that ties it to its audit record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eclusa.corpus.manifest import Manifest, Status
from eclusa.index.chunks import Chunk
from eclusa.ingest.segment import Segment
from eclusa.service.outcomes import DELIVERABLE, Outcome, RefusalReason


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str  # "circular-3978-2020@v5"
    chunk_id: str  # must be one of the chunks retrieved for this request
    locator: str  # "art. 70, caput" — must be a citation of a segment inside that chunk


class Statement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)
    citations: tuple[Citation, ...] = Field(min_length=1)


class Gap(BaseModel):
    """What the corpus does not cover, said explicitly — the whole point of ``partial``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)  # "procedimentos para a compra de ouro"
    where: str | None = None  # "Instrução Normativa BCB nº 406/2023, fora deste corpus"


class Draft(BaseModel):
    """The model's proposed answer, before verification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: Literal["answered", "partial", "refused"]
    statements: tuple[Statement, ...] = ()
    gaps: tuple[Gap, ...] = ()
    refusal_reason: Literal["not_in_corpus", "ambiguous", "out_of_scope"] | None = None
    refusal_note: str | None = None  # names the ambiguity, or what the corpus would need to hold

    @model_validator(mode="after")
    def _shape_matches_outcome(self) -> Draft:
        if self.outcome == "answered" and (not self.statements or self.gaps):
            raise ValueError("answered: at least one statement and no gaps")
        if self.outcome == "partial" and (not self.statements or not self.gaps):
            raise ValueError("partial: at least one statement and at least one declared gap")
        if self.outcome == "refused" and (self.statements or not self.refusal_reason):
            raise ValueError("refused: no statements, and a reason")
        if self.outcome != "refused" and self.refusal_reason:
            raise ValueError("a refusal reason belongs to a refusal")
        return self


@dataclass(frozen=True)
class Violation:
    rule: str
    detail: str


@dataclass(frozen=True)
class Retrieved:
    """What retrieval handed to the model for this request; the only citable universe."""

    chunks: tuple[Chunk, ...]
    segments: dict[str, list[Segment]]  # doc_id -> its segments, to resolve locators

    def chunk(self, chunk_id: str) -> Chunk | None:
        return next((c for c in self.chunks if c.chunk_id == chunk_id), None)

    def locators_in(self, chunk: Chunk) -> set[str]:
        segs = self.segments[chunk.doc_id]
        return {segs[i].citation for i in chunk.segment_indexes if segs[i].citation}


def verify(draft: Draft, retrieved: Retrieved, manifest: Manifest) -> list[Violation]:
    """Every violation found, or an empty list: the draft is an answer."""
    violations: list[Violation] = []
    for n, statement in enumerate(draft.statements, start=1):
        cited_docs: set[str] = set()
        for c in statement.citations:
            problem = _resolve(c, retrieved, manifest)
            if problem:
                violations.append(Violation(problem[0], f"statement {n}: {problem[1]}"))
            else:
                cited_docs.add(c.doc_id)
        violations.extend(_version_rules(n, cited_docs, statement, retrieved, manifest))
    return violations


def _resolve(c: Citation, retrieved: Retrieved, manifest: Manifest) -> tuple[str, str] | None:
    try:
        manifest.by_id(c.doc_id)
    except KeyError:
        return "unknown_document", f"{c.doc_id} is not in the corpus"
    chunk = retrieved.chunk(c.chunk_id)
    if chunk is None:
        return "not_retrieved", f"{c.chunk_id} was not retrieved for this request"
    if chunk.doc_id != c.doc_id:
        return "chunk_document_mismatch", f"{c.chunk_id} belongs to {chunk.doc_id}, not {c.doc_id}"
    if chunk.kind == "notice":
        return None  # the revocation notice has no locator; citing it is citing the notice
    if c.locator not in retrieved.locators_in(chunk):
        return "locator_not_in_chunk", f"{c.locator!r} is not a device inside {c.chunk_id}"
    return None


def _version_rules(
    n: int,
    cited_docs: set[str],
    statement: Statement,
    retrieved: Retrieved,
    manifest: Manifest,
) -> list[Violation]:
    out: list[Violation] = []
    docs = [manifest.by_id(d) for d in sorted(cited_docs)]
    for doc in docs:
        if doc.status is Status.SUPERSEDED and doc.superseded_by not in cited_docs:
            out.append(
                Violation(
                    "superseded_without_current",
                    f"statement {n}: cites {doc.doc_id} (superseded) without {doc.superseded_by}",
                )
            )
    revoked = [d for d in docs if d.status is Status.REVOKED]
    if revoked and all(d.status is Status.REVOKED for d in docs):
        cites_notice = any(
            (chunk := retrieved.chunk(c.chunk_id)) is not None and chunk.kind == "notice"
            for c in statement.citations
        )
        if not cites_notice:
            out.append(
                Violation(
                    "revoked_without_notice",
                    f"statement {n}: supported only by revoked text; the revocation must be cited",
                )
            )
    return out


class Response(BaseModel):
    """What leaves the lock."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    outcome: Outcome
    draft: Draft | None = None  # the verified draft, for answered and partial
    refusal_reason: RefusalReason | None = None
    refusal_note: str | None = None

    @model_validator(mode="after")
    def _deliverable(self) -> Response:
        if self.outcome not in DELIVERABLE:
            raise ValueError(f"{self.outcome} never leaves the lock as an outcome; it is a refusal")
        if self.outcome in (Outcome.ANSWERED, Outcome.PARTIAL):
            if self.draft is None or self.draft.outcome != self.outcome.value:
                raise ValueError(
                    f"{self.outcome}: a verified draft with the same outcome is required"
                )
        elif self.refusal_reason is None:
            raise ValueError(f"{self.outcome}: a refusal reason is required")
        return self


@dataclass(frozen=True)
class Enforced:
    response: Response  # what the caller receives
    outcome: Outcome  # what the audit record says happened
    violations: tuple[Violation, ...]
    blocked: Draft | None  # the draft that did not cross, kept as evidence that the gate worked


def enforce(request_id: str, draft: Draft, retrieved: Retrieved, manifest: Manifest) -> Enforced:
    """Turn a draft into what the caller receives, and keep the evidence for the audit record.

    A draft that fails verification never reaches the caller: it becomes a refusal with
    reason ``contract_violation``, and the audit outcome is ``contract_violation``, not
    ``refused`` — the trail records what happened, not how it was dressed. The blocked
    draft travels with the result: "the model tried to say X and was stopped" is the most
    valuable record this system produces, and nothing crosses unrecorded includes what did
    not cross.
    """
    violations = tuple(verify(draft, retrieved, manifest))
    if violations:
        response = Response(
            request_id=request_id,
            outcome=Outcome.REFUSED,
            refusal_reason=RefusalReason.CONTRACT_VIOLATION,
            refusal_note="; ".join(f"{v.rule}: {v.detail}" for v in violations),
        )
        return Enforced(response, Outcome.CONTRACT_VIOLATION, violations, draft)
    if draft.outcome == "refused":
        response = Response(
            request_id=request_id,
            outcome=Outcome.REFUSED,
            refusal_reason=RefusalReason(draft.refusal_reason),
            refusal_note=draft.refusal_note,
        )
        return Enforced(response, Outcome.REFUSED, (), None)
    outcome = Outcome(draft.outcome)
    delivered = Response(request_id=request_id, outcome=outcome, draft=draft)
    return Enforced(delivered, outcome, (), None)


def draft_json_schema() -> dict:
    """The shape the model is asked for, in the strict form the Responses API enforces:
    every property listed as required, nullable where optional, no extra properties."""
    citation = {
        "type": "object",
        "properties": {
            "doc_id": {"type": "string"},
            "chunk_id": {"type": "string"},
            "locator": {"type": "string"},
        },
        "required": ["doc_id", "chunk_id", "locator"],
        "additionalProperties": False,
    }
    statement = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "citations": {"type": "array", "items": citation},
        },
        "required": ["text", "citations"],
        "additionalProperties": False,
    }
    gap = {
        "type": "object",
        "properties": {"text": {"type": "string"}, "where": {"type": ["string", "null"]}},
        "required": ["text", "where"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "outcome": {"type": "string", "enum": ["answered", "partial", "refused"]},
            "statements": {"type": "array", "items": statement},
            "gaps": {"type": "array", "items": gap},
            "refusal_reason": {
                "type": ["string", "null"],
                "enum": ["not_in_corpus", "ambiguous", "out_of_scope", None],
            },
            "refusal_note": {"type": ["string", "null"]},
        },
        "required": ["outcome", "statements", "gaps", "refusal_reason", "refusal_note"],
        "additionalProperties": False,
    }
