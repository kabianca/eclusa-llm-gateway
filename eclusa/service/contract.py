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
    resolved: list[tuple[int, tuple[Citation, ...]]] = []
    for n, statement in enumerate(draft.statements, start=1):
        good: list[Citation] = []
        for c in statement.citations:
            problem = _resolve(c, retrieved, manifest)
            if problem:
                violations.append(Violation(problem[0], f"statement {n}: {problem[1]}"))
            else:
                good.append(c)
        resolved.append((n, tuple(good)))
    violations.extend(_version_rules(resolved, retrieved, manifest))
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
    resolved: list[tuple[int, tuple[Citation, ...]]],
    retrieved: Retrieved,
    manifest: Manifest,
) -> list[Violation]:
    """The two obligations a moving text creates. They fall on the *answer*, not on the sentence.

    Written per statement at first, which the first live run showed to be wrong: the model
    said "the original provided 1º de julho" in one statement and "the text in force provides
    1º de outubro" in the next, citing each where it belonged, and was refused. That is better
    prose than cramming both citations into one sentence, and it satisfies what the rules are
    for. What must hold is that the answer never rests on superseded or revoked text alone;
    which sentence carries the counterpart is the model's business.

    The superseded rule is matched per *locator*, not merely per act, so that citing the old
    art. 70 is answered by the current art. 70 and not by any other provision of the act.
    """
    out: list[Violation] = []
    everything = [c for _, cs in resolved for c in cs]
    cited = {(c.doc_id, c.locator) for c in everything}
    notices = {
        manifest.by_id(c.doc_id).act_id
        for c in everything
        if (chunk := retrieved.chunk(c.chunk_id)) is not None and chunk.kind == "notice"
    }
    for n, citations in resolved:
        docs = [manifest.by_id(c.doc_id) for c in citations]
        for c, doc in zip(citations, docs, strict=True):
            if doc.status is Status.SUPERSEDED and (doc.superseded_by, c.locator) not in cited:
                out.append(
                    Violation(
                        "superseded_without_current",
                        f"statement {n}: cites {doc.doc_id} {c.locator} (superseded) and the "
                        f"answer never cites {doc.superseded_by} {c.locator}",
                    )
                )
        if docs and all(d.status is Status.REVOKED for d in docs):
            for act in sorted({d.act_id for d in docs} - notices):
                out.append(
                    Violation(
                        "revoked_without_notice",
                        f"statement {n}: rests only on revoked text and the answer never cites "
                        f"the revocation of {act}",
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
