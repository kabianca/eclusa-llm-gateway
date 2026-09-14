"""The output contract: three outcomes, citation required or refuse, and the two rules
that keep a moving text honest — superseded needs current, revoked needs its notice.

Retrieval here is real (the corpus segments and the chunker) so that citations resolve
against actual chunks; the model is not involved.
"""

import pytest
from pydantic import ValidationError

from eclusa.index.chunks import chunk_document
from eclusa.ingest.extract import load_paragraphs
from eclusa.ingest.segment import segment
from eclusa.service.contract import (
    Citation,
    Draft,
    Gap,
    Response,
    Retrieved,
    Statement,
    draft_json_schema,
    enforce,
    verify,
)
from eclusa.service.outcomes import Outcome, RefusalReason


def words(text: str) -> int:
    return len(text.split())


@pytest.fixture(scope="module")
def world(manifest, corpus_dir):
    """Segments and chunks for the documents these tests cite."""
    ids = (
        "circular-3978-2020@v1",
        "circular-3978-2020@v5",
        "circular-3461-2009@v10",
        "carta-circular-4001-2020@v4",
    )
    segments, chunks = {}, {}
    for doc_id in ids:
        doc = manifest.by_id(doc_id)
        segments[doc_id] = segment(doc_id, load_paragraphs(corpus_dir / doc.text_path))
        chunks[doc_id] = chunk_document(doc, manifest, segments[doc_id], words)
    return segments, chunks


def chunk_for(chunks, doc_id, citation=None, kind="unit"):
    return next(
        c for c in chunks[doc_id] if c.kind == kind and (citation is None or c.citation == citation)
    )


def retrieved(world, *chunks):
    return Retrieved(chunks=tuple(chunks), segments=world[0])


def cite(chunk, locator):
    return Citation(doc_id=chunk.doc_id, chunk_id=chunk.chunk_id, locator=locator)


# --- the shape of a draft ---------------------------------------------------------------------


def test_answered_needs_statements_with_citations_and_no_gaps():
    c = Citation(doc_id="d@v1", chunk_id="d@v1#0001", locator="art. 1º, caput")
    Draft(outcome="answered", statements=(Statement(text="x", citations=(c,)),))
    with pytest.raises(ValidationError, match="at least one statement and no gaps"):
        Draft(outcome="answered")
    with pytest.raises(ValidationError, match="at least one statement and no gaps"):
        Draft(
            outcome="answered",
            statements=(Statement(text="x", citations=(c,)),),
            gaps=(Gap(text="g"),),
        )
    with pytest.raises(ValidationError):
        Statement(text="x", citations=())


def test_partial_is_a_first_class_outcome_that_must_declare_its_gap():
    c = Citation(doc_id="d@v1", chunk_id="d@v1#0001", locator="art. 1º, caput")
    ok = Draft(
        outcome="partial",
        statements=(Statement(text="covered", citations=(c,)),),
        gaps=(Gap(text="not covered", where="IN BCB 406/2023, fora deste corpus"),),
    )
    assert ok.gaps[0].where.endswith("fora deste corpus")
    with pytest.raises(ValidationError, match="at least one declared gap"):
        Draft(outcome="partial", statements=(Statement(text="covered", citations=(c,)),))


def test_refused_carries_a_reason_and_no_statements():
    Draft(outcome="refused", refusal_reason="not_in_corpus", refusal_note="nada sobre o tema")
    with pytest.raises(ValidationError, match="no statements, and a reason"):
        Draft(outcome="refused")
    c = Citation(doc_id="d@v1", chunk_id="d@v1#0001", locator="art. 1º, caput")
    with pytest.raises(ValidationError, match="belongs to a refusal"):
        Draft(
            outcome="answered",
            statements=(Statement(text="x", citations=(c,)),),
            refusal_reason="ambiguous",
        )


# --- citations resolve, or it is a violation -------------------------------------------------


def test_a_citation_must_name_a_corpus_document_a_retrieved_chunk_and_a_device_in_it(
    manifest, world
):
    _, chunks = world
    art70 = chunk_for(chunks, "circular-3978-2020@v5", "art. 70, caput")
    other = chunk_for(chunks, "circular-3978-2020@v5", "art. 1º, caput")
    ok = Draft(
        outcome="answered",
        statements=(
            Statement(
                text="Entra em vigor em 1º/10/2020.", citations=(cite(art70, "art. 70, caput"),)
            ),
        ),
    )
    assert verify(ok, retrieved(world, art70), manifest) == []

    unknown = ok.model_copy(
        update={
            "statements": (
                Statement(
                    text="x",
                    citations=(
                        Citation(
                            doc_id="circular-9-2099@v1",
                            chunk_id=art70.chunk_id,
                            locator="art. 70, caput",
                        ),
                    ),
                ),
            )
        }
    )
    assert [v.rule for v in verify(unknown, retrieved(world, art70), manifest)] == [
        "unknown_document"
    ]

    not_retrieved = verify(ok, retrieved(world, other), manifest)
    assert [v.rule for v in not_retrieved] == ["not_retrieved"]

    wrong_locator = ok.model_copy(
        update={"statements": (Statement(text="x", citations=(cite(art70, "art. 69, caput"),)),)}
    )
    assert [v.rule for v in verify(wrong_locator, retrieved(world, art70), manifest)] == [
        "locator_not_in_chunk"
    ]


def test_a_deep_locator_resolves_inside_its_split_piece(manifest, world):
    segments, chunks = world
    piece = next(
        c
        for c in chunks["circular-3978-2020@v5"]
        if c.citation == "art. 24, § 3º"
        and any(
            segments[c.doc_id][i].citation == "art. 24, § 3º, VI, g, 2" for i in c.segment_indexes
        )
    )
    deep = cite(piece, "art. 24, § 3º, VI, g, 2")
    draft = Draft(
        outcome="answered", statements=(Statement(text="Cem cotistas.", citations=(deep,)),)
    )
    assert verify(draft, retrieved(world, piece), manifest) == []
    elsewhere = Draft(
        outcome="answered",
        statements=(Statement(text="x", citations=(cite(piece, "art. 24, § 3º, I"),)),),
    )
    rules = [v.rule for v in verify(elsewhere, retrieved(world, piece), manifest)]
    assert rules == ["locator_not_in_chunk"], "inciso I sits in another piece of the same unit"


# --- the two rules for a text that moves -----------------------------------------------------


def test_citing_the_original_wording_requires_citing_the_version_in_force(manifest, world):
    _, chunks = world
    v1 = chunk_for(chunks, "circular-3978-2020@v1", "art. 70, caput")
    v5 = chunk_for(chunks, "circular-3978-2020@v5", "art. 70, caput")
    only_original = Draft(
        outcome="answered",
        statements=(
            Statement(
                text="Entra em vigor em 1º de julho de 2020.",
                citations=(cite(v1, "art. 70, caput"),),
            ),
        ),
    )
    rules = [v.rule for v in verify(only_original, retrieved(world, v1, v5), manifest)]
    assert rules == ["superseded_without_current"], (
        "julho with total confidence is exactly the error"
    )
    both = Draft(
        outcome="answered",
        statements=(
            Statement(
                text="Entra em vigor em 1º/10/2020; o texto original previa 1º de julho.",
                citations=(cite(v5, "art. 70, caput"), cite(v1, "art. 70, caput")),
            ),
        ),
    )
    assert verify(both, retrieved(world, v1, v5), manifest) == []


def test_answering_from_a_revoked_act_requires_citing_its_revocation(manifest, world):
    _, chunks = world
    art4 = chunk_for(chunks, "circular-3461-2009@v10", "art. 4º, caput")
    notice = chunk_for(chunks, "circular-3461-2009@v10", kind="notice")
    silent = Draft(
        outcome="answered",
        statements=(Statement(text="A 3.461 exige...", citations=(cite(art4, "art. 4º, caput"),)),),
    )
    assert [v.rule for v in verify(silent, retrieved(world, art4, notice), manifest)] == [
        "revoked_without_notice"
    ]
    stated = Draft(
        outcome="answered",
        statements=(
            Statement(
                text="A Circular 3.461 exigia...; revogada pela 3.978 a partir de 1º/10/2020.",
                citations=(cite(art4, "art. 4º, caput"), cite(notice, "revogação")),
            ),
        ),
    )
    assert verify(stated, retrieved(world, art4, notice), manifest) == []


# --- what leaves the lock ---------------------------------------------------------------------


def test_the_gold_question_is_the_partial_showcase(manifest, world):
    _, chunks = world
    piece = next(
        c
        for c in chunks["carta-circular-4001-2020@v4"]
        if any(world[0][c.doc_id][i].citation == "art. 1º, XIX" for i in c.segment_indexes)
    )
    draft = Draft(
        outcome="partial",
        statements=(
            Statement(
                text="O corpus lista indícios ligados ao mercado de ouro (CC 4.001, art. 1º, XIX).",
                citations=(cite(piece, "art. 1º, XIX"),),
            ),
        ),
        gaps=(
            Gap(
                text="procedimentos para a compra de ouro",
                where="Instrução Normativa BCB nº 406/2023, fora deste corpus",
            ),
        ),
    )
    result = enforce("req-1", draft, retrieved(world, piece), manifest)
    assert result.outcome is Outcome.PARTIAL and result.response.outcome is Outcome.PARTIAL
    assert (
        result.response.draft.gaps[0].where
        == "Instrução Normativa BCB nº 406/2023, fora deste corpus"
    )
    assert result.blocked is None and result.violations == ()


def test_a_violating_draft_never_reaches_the_caller(manifest, world):
    _, chunks = world
    v1 = chunk_for(chunks, "circular-3978-2020@v1", "art. 70, caput")
    draft = Draft(
        outcome="answered",
        statements=(
            Statement(text="1º de julho de 2020.", citations=(cite(v1, "art. 70, caput"),)),
        ),
    )
    result = enforce("req-2", draft, retrieved(world, v1), manifest)
    response = result.response
    assert response.outcome is Outcome.REFUSED
    assert response.refusal_reason is RefusalReason.CONTRACT_VIOLATION
    assert response.draft is None, "the draft is not delivered"
    assert "superseded_without_current" in response.refusal_note
    assert result.outcome is Outcome.CONTRACT_VIOLATION, "the trail records what happened"
    assert result.blocked == draft, "what the model tried to say is kept as evidence"
    assert [v.rule for v in result.violations] == ["superseded_without_current"]


def test_a_refusal_passes_through_with_its_reason(manifest, world):
    draft = Draft(outcome="refused", refusal_reason="ambiguous", refusal_note="qual circular?")
    result = enforce("req-3", draft, retrieved(world), manifest)
    assert result.outcome is Outcome.REFUSED and result.blocked is None
    response = result.response
    assert response.refusal_reason is RefusalReason.AMBIGUOUS
    assert response.refusal_note == "qual circular?"


def test_the_json_schema_asked_of_the_model_matches_the_draft_model():
    schema = draft_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"]), "strict mode: every key required"
    citation = {"doc_id": "d@v1", "chunk_id": "d@v1#0001", "locator": "art. 1º, caput"}
    example = {
        "outcome": "partial",
        "statements": [{"text": "x", "citations": [citation]}],
        "gaps": [{"text": "y", "where": None}],
        "refusal_reason": None,
        "refusal_note": None,
    }
    Draft.model_validate(example)


def test_response_shape_is_enforced():
    with pytest.raises(ValidationError, match="verified draft"):
        Response(request_id="r", outcome=Outcome.ANSWERED)
    with pytest.raises(ValidationError, match="refusal reason is required"):
        Response(request_id="r", outcome=Outcome.REFUSED)
    with pytest.raises(ValidationError, match="never leaves the lock"):
        Response(request_id="r", outcome=Outcome.BUDGET_EXCEEDED, refusal_reason="budget_exceeded")
