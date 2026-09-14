"""Version-aware retrieval: the four decisions of eclusa/index/retrieve.py, on the small index.

The aggregate evidence is the frozen evaluation (eval/retrieval/results-before.json and
results-after.json); these tests pin the mechanism so a future change cannot quietly undo it.
"""

from eclusa.corpus.manifest import Status
from eclusa.index.retrieve import body_of, mentioned_acts, retrieve

VERSION_QUESTION = "Quando a Circular 3.978 entra em vigor?"


def test_the_version_in_force_ranks_first_and_the_original_follows_only_when_it_differs(
    manifest, small_index, embedder
):
    chunks = retrieve(VERSION_QUESTION, small_index, embedder, manifest, k=8)
    art70 = [c for c in chunks if c.citation == "art. 70, caput"]
    assert [c.doc_id for c in art70] == ["circular-3978-2020@v5", "circular-3978-2020@v1"], (
        "consolidated first, then the original as history, because the wording differs"
    )
    assert body_of(art70[0]) != body_of(art70[1])

    chunks = retrieve(
        "Qual é o objetivo da avaliação interna de risco?", small_index, embedder, manifest, k=8
    )
    art10 = [c for c in chunks if c.citation == "art. 10, caput"]
    assert [c.doc_id for c in art10] == ["circular-3978-2020@v5"], (
        "identical wording in both versions: the superseded copy is noise and is not emitted"
    )


def test_a_unit_that_only_the_superseded_text_matches_still_brings_the_text_in_force(
    manifest, small_index, embedder
):
    # Art. 68 in force is "(Revogado pela Resolução BCB nº 282...)" — nothing like the
    # question; the original art. 68 amends Circular 3.691 and matches. The group brings
    # the version in force first anyway: same act, same unit.
    chunks = retrieve(
        "A Circular 3.978 altera a Circular 3.691 sobre o mercado de câmbio?",
        small_index,
        embedder,
        manifest,
        k=8,
    )
    art68 = [c for c in chunks if c.citation == "art. 68, caput"]
    assert [c.doc_id for c in art68][:2] == ["circular-3978-2020@v5", "circular-3978-2020@v1"]


def test_revoked_acts_rank_below_acts_in_force_unless_the_question_names_them(
    manifest, small_index, embedder
):
    question = (
        "As instituições devem obter informações para caracterizar clientes "
        "como pessoas expostas politicamente?"
    )
    chunks = retrieve(question, small_index, embedder, manifest, k=8)
    statuses = [manifest.by_id(c.doc_id).status for c in chunks]
    first_revoked = statuses.index(Status.REVOKED) if Status.REVOKED in statuses else len(statuses)
    assert all(s is not Status.REVOKED for s in statuses[:first_revoked])
    assert chunks[0].doc_id == "circular-3978-2020@v5"

    named = retrieve(
        "O que a Circular 3.461 dizia sobre pessoas expostas politicamente?",
        small_index,
        embedder,
        manifest,
        k=8,
    )
    assert named[0].doc_id == "circular-3461-2009@v10", "the act asked about is what comes first"
    assert mentioned_acts("O que a Circular 3.461 dizia?", manifest) == {"circular-3461-2009"}
    assert mentioned_acts("Circular 3461 e Resolução 119", manifest) == {
        "circular-3461-2009",
        "resolucao-bcb-119-2021",
    }
    assert mentioned_acts("Quando entra em vigor?", manifest) == set()


def test_a_revoked_act_never_enters_without_its_revocation_notice(manifest, small_index, embedder):
    chunks = retrieve(
        "O que a Circular 3.461 dizia sobre pessoas expostas politicamente?",
        small_index,
        embedder,
        manifest,
        k=8,
    )
    revoked = [
        i
        for i, c in enumerate(chunks)
        if c.doc_id == "circular-3461-2009@v10" and c.kind != "notice"
    ]
    notice = [
        i
        for i, c in enumerate(chunks)
        if c.doc_id == "circular-3461-2009@v10" and c.kind == "notice"
    ]
    assert revoked and notice, "the revoked text and its notice are both within reach"
    assert notice[0] == revoked[0] + 1, "the notice follows the first revoked passage"
    assert len(chunks) == 8 and len({c.chunk_id for c in chunks}) == 8


def test_retrieval_is_deterministic_and_never_exceeds_k(manifest, small_index, embedder):
    a = retrieve(VERSION_QUESTION, small_index, embedder, manifest, k=5)
    b = retrieve(VERSION_QUESTION, small_index, embedder, manifest, k=5)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b] and len(a) == 5
