"""Retrieval, tested for the properties the thesis needs: the model is the pinned model,
embedding is reproducible, every citable segment is reachable through exactly one kind
of chunk, search is exact and ties are decisions.

Tests that need the model download it through the pinned fetcher (cached after the
first run; CI caches the Hub directory keyed on the revision). Nothing here skips.
"""

from pathlib import Path

import numpy as np
import pytest

from eclusa.index import embedding
from eclusa.index.chunks import (
    BODY_KINDS,
    HEAD_KINDS,
    Chunk,
    chunk_document,
    is_embeddable,
    version_label,
)
from eclusa.index.store import IndexStore, build
from eclusa.ingest.extract import load_paragraphs
from eclusa.ingest.segment import segment


def words(text: str) -> int:
    return len(text.split())


@pytest.fixture(scope="module")
def segmented(manifest, corpus_dir: Path):
    return {
        d.doc_id: segment(d.doc_id, load_paragraphs(corpus_dir / d.text_path))
        for d in manifest.documents
    }


@pytest.fixture(scope="module")
def chunked(manifest, segmented) -> dict[str, list[Chunk]]:
    return {
        d.doc_id: chunk_document(d, manifest, segmented[d.doc_id], words)
        for d in manifest.documents
    }


@pytest.fixture(scope="module")
def embedder() -> embedding.Embedder:
    # Threads do not change the bytes on the dev machine (measured 1 vs 4); the
    # reproducibility test below asserts it again wherever the suite runs.
    return embedding.Embedder.pinned(threads=4)


# --- chunks: what retrieval can return ----------------------------------------------------


def test_every_embeddable_segment_is_reachable_and_nothing_else_is(segmented, chunked):
    for doc_id, segs in segmented.items():
        reachable = {i for c in chunked[doc_id] for i in c.segment_indexes}
        assert reachable == {s.index for s in segs if is_embeddable(s)}, doc_id
        for c in chunked[doc_id]:
            kinds = {segs[i].kind for i in c.segment_indexes}
            assert not kinds & {"preamble", "heading", "quoted", "closing", "annex"}, (
                doc_id,
                c.chunk_id,
            )


def test_chunk_ids_are_unique_and_deterministic(manifest, segmented, chunked):
    for d in manifest.documents:
        ids = [c.chunk_id for c in chunked[d.doc_id]]
        assert len(ids) == len(set(ids)), d.doc_id
        again = chunk_document(d, manifest, segmented[d.doc_id], words)
        assert again == chunked[d.doc_id], d.doc_id


def test_a_unit_over_budget_is_split_and_every_piece_repeats_the_head(manifest, segmented):
    doc = manifest.by_id("carta-circular-4001-2020@v4")
    chunks = chunk_document(doc, manifest, segmented[doc.doc_id], words, budget=120)
    pieces = [c for c in chunks if c.chunk_id.startswith(f"{doc.doc_id}#0011.")]
    assert len(pieces) > 5, "art. 1º with 19 incisos and 166 alíneas does not fit in 120 words"
    head = segmented[doc.doc_id][11]
    assert head.kind == "caput" and head.locator.article == "1"
    for piece in pieces:
        assert piece.segment_indexes[0] == head.index
        assert piece.citation == "art. 1º, caput"
        assert head.text in piece.text
        assert words(piece.text) <= 120 or len(piece.segment_indexes) == 2, (
            "one device can exceed alone"
        )


def test_both_versions_of_3978_have_an_art_70_chunk_that_names_the_version(chunked):
    v1 = next(c for c in chunked["circular-3978-2020@v1"] if c.citation == "art. 70, caput")
    v5 = next(c for c in chunked["circular-3978-2020@v5"] if c.citation == "art. 70, caput")
    assert "texto original, superado pela versão consolidada" in v1.text
    assert "texto consolidado, em vigor" in v5.text
    assert "1º de julho de 2020" in v1.text and "1º de outubro de 2020" in v5.text


def test_revocation_notice_is_its_own_chunk_naming_the_revoking_act(manifest, chunked):
    notices = [c for c in chunked["circular-3461-2009@v10"] if c.kind == "notice"]
    assert len(notices) == 1
    assert notices[0].citation is None
    assert "revogada pela Circular nº 3.978 a partir de 01/10/2020" in notices[0].text
    assert version_label(manifest.by_id("circular-3942-2019@v2"), manifest).startswith(
        "revogada pela Resolução BCB nº 44"
    )


def test_amending_acts_contribute_only_their_own_articles(segmented, chunked):
    # Resolução BCB 119 quotes the new wording of 3.978 arts. 16, 18, 24, 33; none of that
    # is embedded — it would compete with the consolidated text, which carries the marker.
    chunks = chunked["resolucao-bcb-119-2021@v1"]
    assert [c.citation for c in chunks] == ["art. 1º, caput", "art. 2º, caput"]
    assert not any(
        "quoted" == segmented["resolucao-bcb-119-2021@v1"][i].kind
        for c in chunks
        for i in c.segment_indexes
    )


def test_head_and_body_kinds_cover_the_locatable_devices():
    assert set(HEAD_KINDS) == {"caput", "paragraph"}
    assert set(BODY_KINDS) == {"inciso", "alinea", "item", "note", "continuation"}


# --- the model is the pinned model, and embedding is reproducible --------------------------


def test_pinned_model_files_have_the_recorded_hashes():
    paths = embedding.fetch_model()
    assert set(paths) == set(embedding.MODEL_FILES)
    for filename, path in paths.items():
        assert embedding.sha256_of(path) == embedding.MODEL_FILES[filename]
        assert embedding.MODEL_REVISION in str(path)


def test_embeddings_are_unit_length_384_and_bitwise_reproducible(embedder):
    texts = ["Art. 70. Esta Circular entra em vigor em 1º de julho de 2020.", "I - dos clientes;"]
    a = embedder.embed_passages(texts)
    b = embedder.embed_passages(texts)
    assert a.shape == (2, embedding.DIMENSION) and a.dtype == np.float32
    assert np.allclose(np.linalg.norm(a, axis=1), 1.0, atol=1e-5)
    assert np.array_equal(a, b), "same text, same bytes"
    single = embedder.embed_passages(texts[:1])
    assert np.array_equal(a[:1], single), "batch composition does not change a vector"


def test_query_and_passage_prefixes_are_applied(embedder):
    text = "prazo para comunicar ao Coaf"
    q = embedder.embed_query(text)
    p = embedder.embed_passages([text])[0]
    assert not np.array_equal(q, p), "the model card's prefixes make query and passage differ"
    assert embedder.token_count("x") > 1, "the prefix counts toward the budget"


# --- exact search, decided ties, reproducible artifact ------------------------------------


def test_search_breaks_exact_ties_by_chunk_id():
    vectors = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    chunks = tuple(
        Chunk(chunk_id=i, doc_id="d", kind="unit", citation=None, segment_indexes=(0,), text="")
        for i in ("z#0002", "a#0001", "m#0003")
    )
    store = IndexStore(vectors, chunks, {})
    hits = store.search(np.array([1.0, 0.0], dtype=np.float32), k=3)
    assert [h.chunk.chunk_id for h in hits] == ["a#0001", "z#0002", "m#0003"]
    assert hits[0].score == hits[1].score == 1.0
    noise = np.array([[1.0, 0.0], [1.0 - 1e-9, 0.0]], dtype=np.float32)
    store = IndexStore(noise, chunks[:2], {})
    hits = store.search(np.array([1.0, 0.0], dtype=np.float32), k=2)
    assert [h.chunk.chunk_id for h in hits] == ["a#0001", "z#0002"], "sub-rounding noise is a tie"


def test_index_build_is_reproducible_and_round_trips(manifest, corpus_dir, embedder, tmp_path):
    small = manifest.model_copy(
        update={
            "documents": tuple(
                manifest.by_id(i) for i in ("circular-4005-2020@v1", "resolucao-bcb-282-2022@v1")
            )
        }
    )
    first = build(small, corpus_dir, embedder, corpus_dir / "manifest.json")
    second = build(small, corpus_dir, embedder, corpus_dir / "manifest.json")
    assert np.array_equal(first.vectors, second.vectors) and first.chunks == second.chunks
    first.save(tmp_path / "a")
    second.save(tmp_path / "b")
    for name in ("vectors.npy", "chunks.jsonl", "meta.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name
    loaded = IndexStore.load(tmp_path / "a")
    assert np.array_equal(loaded.vectors, first.vectors) and loaded.chunks == first.chunks
    assert loaded.meta["model_revision"] == embedding.MODEL_REVISION
    assert loaded.meta["chunk_policy"] == "units-v1" and "built_at" not in loaded.meta


@pytest.mark.slow
def test_retrieval_reaches_both_versions_of_the_entry_into_force_article(
    manifest, corpus_dir, embedder
):
    # The demonstration case, at the retrieval layer: both art. 70 texts must be within
    # reach, so that the answer can cite the consolidated one and name the original. Which
    # of the two ranks first is the open engineering problem, not asserted here.
    both = manifest.model_copy(
        update={
            "documents": tuple(
                manifest.by_id(i) for i in ("circular-3978-2020@v1", "circular-3978-2020@v5")
            )
        }
    )
    store = build(both, corpus_dir, embedder, corpus_dir / "manifest.json")
    hits = store.search(embedder.embed_query("Quando a Circular 3.978 entra em vigor?"), k=8)
    found = {(h.chunk.doc_id, h.chunk.citation) for h in hits}
    assert ("circular-3978-2020@v5", "art. 70, caput") in found
    assert ("circular-3978-2020@v1", "art. 70, caput") in found
