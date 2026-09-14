"""The index: exact search over the chunk vectors, deterministic by construction.

Not FAISS, not HNSW, not IVF — not because the corpus is small (it is) but
because approximate search is not reproducible: an approximate index returns
slightly different neighbours depending on how it was built. A project whose
thesis is "pin what moves" cannot have retrieval that moves. A dot product over
every vector is deterministic by construction.

The caveat that comes with it: floating-point summation depends on the BLAS
implementation, so two environments can differ in the last bits of a score and
invert ties. Scores are therefore rounded before ranking and ties are broken by
chunk id, never left to numerical noise. A tie is a decision, not chance.

The artifact on disk carries no timestamp: the same corpus, the same model and
the same policy produce the same bytes, and a test asserts it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from eclusa.corpus.manifest import Manifest
from eclusa.index.chunks import POLICY, TOKEN_BUDGET, Chunk, chunk_document
from eclusa.index.embedding import Embedder
from eclusa.ingest.extract import load_paragraphs
from eclusa.ingest.segment import segment

SCORE_DECIMALS = 6


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float  # rounded cosine similarity (vectors are unit length)


@dataclass(frozen=True)
class IndexStore:
    vectors: np.ndarray  # (n, dimension) float32, unit length
    chunks: tuple[Chunk, ...]
    meta: dict

    def search(self, query: np.ndarray, k: int = 8) -> list[Hit]:
        scores = np.round(self.vectors @ query.astype(np.float32), SCORE_DECIMALS)
        order = sorted(range(len(self.chunks)), key=lambda i: (-scores[i], self.chunks[i].chunk_id))
        return [Hit(self.chunks[i], float(scores[i])) for i in order[:k]]

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        np.save(directory / "vectors.npy", self.vectors)
        with open(directory / "chunks.jsonl", "w", encoding="utf-8") as fh:
            for c in self.chunks:
                fh.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")
        (directory / "meta.json").write_text(
            json.dumps(self.meta, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, directory: Path) -> IndexStore:
        vectors = np.load(directory / "vectors.npy")
        with open(directory / "chunks.jsonl", encoding="utf-8") as fh:
            chunks = tuple(_chunk_from_json(json.loads(line)) for line in fh if line.strip())
        meta = json.loads((directory / "meta.json").read_text(encoding="utf-8"))
        if len(chunks) != vectors.shape[0]:
            raise ValueError("chunks.jsonl and vectors.npy disagree on the number of chunks")
        return cls(vectors, chunks, meta)


def _chunk_from_json(d: dict) -> Chunk:
    d["segment_indexes"] = tuple(d["segment_indexes"])
    return Chunk(**d)


def build(
    manifest: Manifest, corpus_dir: Path, embedder: Embedder, manifest_path: Path
) -> IndexStore:
    """Segment, chunk and embed the whole corpus. Runs at image build, never at boot."""
    chunks: list[Chunk] = []
    for doc in manifest.documents:
        segments = segment(doc.doc_id, load_paragraphs(corpus_dir / doc.text_path))
        chunks.extend(chunk_document(doc, manifest, segments, embedder.token_count))
    vectors = embedder.embed_passages([c.text for c in chunks])
    info = embedder.info
    meta = {
        "model_id": info.model_id,
        "model_revision": info.revision,
        "model_files": info.files,
        "dimension": info.dimension,
        "chunk_policy": POLICY,
        "token_budget": TOKEN_BUDGET,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "documents": len(manifest.documents),
        "chunks": len(chunks),
    }
    return IndexStore(vectors, tuple(chunks), meta)
