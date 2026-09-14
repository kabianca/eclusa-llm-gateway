"""The frozen retrieval cases are well-formed and every expected unit exists in the corpus —
checked against the corpus text, not against what the retriever returns. The metrics are
computed here on a synthetic ranking so their definitions are pinned independently of any
index."""

import pytest

from eclusa.corpus.manifest import Status
from eclusa.eval.retrieval import aggregate, evaluate_case, load_cases
from eclusa.index.chunks import Chunk, chunk_document
from eclusa.ingest.extract import load_paragraphs
from eclusa.ingest.segment import segment


def test_cases_are_unique_well_typed_and_point_at_real_units(manifest, corpus_dir):
    cases = load_cases()
    assert cases.k == 8, "the gateway's k; the metrics are over the top-8"
    ids = [c.id for c in cases.cases]
    questions = [c.question for c in cases.cases]
    assert len(ids) == len(set(ids)) and len(questions) == len(set(questions))
    units_in_corpus: dict[tuple[str, str], set[str]] = {}
    for d in manifest.documents:
        segs = segment(d.doc_id, load_paragraphs(corpus_dir / d.text_path))
        for c in chunk_document(d, manifest, segs, lambda t: len(t.split())):
            if c.citation:
                units_in_corpus.setdefault((d.act_id, c.citation), set()).add(d.doc_id)
    for case in cases.cases:
        for unit in case.units:
            assert (case.expected_act, unit) in units_in_corpus, (case.id, unit)
        docs = {doc for unit in case.units for doc in units_in_corpus[(case.expected_act, unit)]}
        statuses = {manifest.by_id(doc).status for doc in docs}
        if case.kind in ("changed", "unchanged"):
            # The act exists in two versions and the unit exists in the one in force. Some
            # units exist only there (art. 23-A, art. 28 § 4º, art. 33 parágrafo único were
            # added by amendment): for those the trap is a neighbouring unit of the old text.
            versions = {d.status for d in manifest.versions(case.expected_act)}
            assert versions == {Status.IN_FORCE, Status.SUPERSEDED}, case.id
            assert Status.IN_FORCE in statuses, f"{case.id}: unit missing from the text in force"
        if case.kind == "topic":
            assert case.revoked_act and manifest.current(case.revoked_act) is None, case.id
            assert manifest.current(case.expected_act) is not None, case.id
        if case.kind == "names_revoked":
            assert statuses == {Status.REVOKED}, case.id


def chunk(doc_id: str, citation: str | None, kind: str = "unit") -> Chunk:
    return Chunk(
        chunk_id=f"{doc_id}#{citation}",
        doc_id=doc_id,
        kind=kind,
        citation=citation,
        segment_indexes=(0,),
        text="",
    )


def test_metric_definitions_on_a_synthetic_ranking(manifest):
    cases = {c.id: c for c in load_cases().cases}
    v1, v5, old = "circular-3978-2020@v1", "circular-3978-2020@v5", "circular-3461-2009@v10"

    # changed: the superseded text ranks first -> hit, but not in force first; mrr from v5's rank
    r = evaluate_case(
        cases["changed-70"], [chunk(v1, "art. 70, caput"), chunk(v5, "art. 70, caput")], manifest
    )
    assert r.hit and r.in_force_first is False and r.mrr_in_force == 0.5
    r = evaluate_case(
        cases["changed-70"], [chunk(v5, "art. 70, caput"), chunk(v1, "art. 70, caput")], manifest
    )
    assert r.in_force_first is True and r.mrr_in_force == 1.0
    r = evaluate_case(cases["changed-70"], [chunk(v5, "art. 69, caput")], manifest)
    assert not r.hit and r.in_force_first is False and r.mrr_in_force == 0.0

    # topic: the revoked act above the in-force one fails; absent revoked act passes
    r = evaluate_case(
        cases["topic-pep"], [chunk(old, "art. 4º, caput"), chunk(v5, "art. 27, caput")], manifest
    )
    assert r.hit and r.revoked_below_current is False
    r = evaluate_case(cases["topic-pep"], [chunk(v5, "art. 27, caput")], manifest)
    assert r.revoked_below_current is True
    r = evaluate_case(cases["topic-pep"], [chunk(old, "art. 4º, caput")], manifest)
    assert r.revoked_below_current is False and not r.hit

    # names_revoked: the notice must come along when the revoked text does
    r = evaluate_case(cases["revoked-pep"], [chunk(old, "art. 4º, caput")], manifest)
    assert r.hit and r.notice_with_revoked is False
    r = evaluate_case(
        cases["revoked-pep"], [chunk(old, "art. 4º, caput"), chunk(old, None, "notice")], manifest
    )
    assert r.notice_with_revoked is True

    summary = aggregate(
        [
            evaluate_case(
                cases["changed-70"],
                [chunk(v1, "art. 70, caput"), chunk(v5, "art. 70, caput")],
                manifest,
            ),
            evaluate_case(cases["unchanged-10"], [chunk(v5, "art. 10, caput")], manifest),
        ]
    )
    assert summary["cases"] == 2 and summary["hit@k"] == 1.0
    assert summary["in_force_first"] == 0.5 and summary["mrr_in_force"] == 0.75
    assert summary["in_force_first[changed]"] == 0.0 and summary["in_force_first[unchanged]"] == 1.0


@pytest.mark.slow
def test_version_aware_retrieval_holds_the_frozen_after_numbers(manifest, corpus_dir, embedder):
    # The gate for retrieval, separate from generation: builds the whole index and requires
    # the numbers measured on 2026-09-14 (eval/retrieval/results-after.json). A change that
    # lowers any of them fails here, whatever the model would have answered.
    from eclusa.eval.retrieval import run
    from eclusa.index.retrieve import retrieve
    from eclusa.index.store import build

    store = build(manifest, corpus_dir, embedder, corpus_dir / "manifest.json")
    cases = load_cases()
    summary, _ = run(
        cases,
        store,
        embedder,
        manifest,
        search=lambda q: retrieve(q, store, embedder, manifest, k=cases.k),
    )
    metrics = summary["metrics"]
    assert metrics["in_force_first"] == 1.0
    assert metrics["revoked_below_current"] == 1.0
    assert metrics["notice_with_revoked"] == 1.0
    assert metrics["hit@k"] >= 0.9167
    assert metrics["mrr_in_force"] >= 0.8042
