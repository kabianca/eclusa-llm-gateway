"""The outcomes a request can have. One vocabulary for the contract and the audit trail.

The first design had two answers to a question: answered or refused. The gold
question broke it. Carta Circular 4.001 lists red-flag situations around the gold
market; the corpus has no procedures for buying gold. The honest response is
neither an answer nor a refusal: it says what the corpus covers and declares, in
so many words, what it does not. Most RAG systems answer the covered part and
stay silent about the rest — the most dangerous way of being wrong, because it
looks complete. So *partial* is an outcome of its own, with its own contract
rules, its own audit value and its own tests.

The last two outcomes never leave the lock as answers: a request that would
exceed the budget is stopped before the call, and an answer that violates the
contract is turned into a refusal. Both are recorded as what they were.
"""

from __future__ import annotations

from enum import StrEnum


class Outcome(StrEnum):
    ANSWERED = "answered"  # every statement cites a retrieved passage
    PARTIAL = "partial"  # answers what the corpus covers and declares what it does not
    REFUSED = "refused"  # nothing in the corpus supports an answer, or the question is ambiguous
    BUDGET_EXCEEDED = "budget_exceeded"  # stopped before the call; the caller sees a refusal
    CONTRACT_VIOLATION = "contract_violation"  # the model's draft failed verification; a refusal
    PROVIDER_ERROR = "provider_error"  # the call did not complete; recorded, then raised


class RefusalReason(StrEnum):
    NOT_IN_CORPUS = "not_in_corpus"
    AMBIGUOUS = "ambiguous"
    OUT_OF_SCOPE = "out_of_scope"  # the corpus holds the act but not what was asked of it
    BUDGET_EXCEEDED = "budget_exceeded"
    CONTRACT_VIOLATION = "contract_violation"
    PROVIDER_ERROR = "provider_error"


# What the caller can receive. The failure outcomes surface as refusals with their reason.
DELIVERABLE = (Outcome.ANSWERED, Outcome.PARTIAL, Outcome.REFUSED)
