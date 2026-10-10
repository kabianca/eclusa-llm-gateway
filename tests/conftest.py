from pathlib import Path

import pytest

from eclusa.corpus import manifest as manifest_mod

REPO = Path(__file__).resolve().parent.parent
CORPUS_DIR = REPO / "corpus"


@pytest.fixture(scope="session")
def corpus_dir() -> Path:
    return CORPUS_DIR


@pytest.fixture(scope="session")
def manifest() -> manifest_mod.Manifest:
    return manifest_mod.load(CORPUS_DIR / "manifest.json")


SMALL_INDEX_DOCS = (
    "circular-3978-2020@v1",  # the demonstration case: original ...
    "circular-3978-2020@v5",  # ... and consolidated text of the same act
    "carta-circular-4001-2020@v4",  # the partial showcase (gold, inciso XIX)
    "circular-3461-2009@v10",  # a revoked act, with its revocation notice
    "resolucao-bcb-344-2023@v1",  # an amending act, whose art. 1º transcribes art. 23-A
)


@pytest.fixture(scope="session")
def embedder():
    from eclusa.index.embedding import Embedder

    # Threads do not change the bytes on the dev machine (measured 1 vs 4); the
    # reproducibility test asserts it again wherever the suite runs.
    return Embedder.pinned(threads=4)


@pytest.fixture(scope="session")
def full_index(manifest, embedder):
    """The whole corpus, built once: the recordings were made against this index, so any
    test that replays one needs the same context the live run saw."""
    from eclusa.index.store import build

    return build(manifest, CORPUS_DIR, embedder, CORPUS_DIR / "manifest.json")


@pytest.fixture(scope="session")
def small_index(manifest, embedder):
    """Built once per session: four documents, enough for version, partial and revocation."""
    from eclusa.index.store import build

    small = manifest.model_copy(
        update={"documents": tuple(manifest.by_id(d) for d in SMALL_INDEX_DOCS)}
    )
    return build(small, CORPUS_DIR, embedder, CORPUS_DIR / "manifest.json")
