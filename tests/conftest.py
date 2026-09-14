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
