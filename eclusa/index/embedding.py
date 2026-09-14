"""The embedding model, pinned by name, revision and file hash.

Why local: the question has to be embedded at serving time too, so an embedding
API would need a key just to retrieve, which kills "starts with no network and
no key". Why multilingual: the corpus is Portuguese legal text, and an English
model degrades silently — retrieval still returns *something*. Why pinned three
ways: a model name is a moving target on the Hub; the revision fixes the commit,
and the sha256 of each file fixes the bytes even if the revision were rewritten.

Why ONNX fp32 and not the int8 export: the quantized kernels differ between CPU
feature levels (AVX2 vs AVX512-VNNI), so the same text would embed differently
on different machines. fp32 keeps that to BLAS-level noise, which the search
layer absorbs by rounding scores and breaking ties by id. The cost is honest:
470 MB downloaded once and cached, and carried in the image.

What the model card at this revision says, and this module does: prefix every
passage with "passage: " and every query with "query: ", truncate at 512
tokens, mean-pool the last hidden state over the attention mask, L2-normalise.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MODEL_ID = "intfloat/multilingual-e5-small"
MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"  # 2026-04-02 on the Hub
MODEL_FILES = {
    "onnx/model.onnx": "ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665",
    "onnx/tokenizer.json": "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39",
}
DIMENSION = 384
MAX_TOKENS = 512
BATCH_SIZE = 16  # fixed: padding length depends on the batch, and the build must be reproducible


class ModelPinError(RuntimeError):
    """The files on disk are not the pinned model."""


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch_model(cache_dir: Path | None = None) -> dict[str, Path]:
    """Download (or find in the cache) the pinned files and verify their hashes.

    Network only on a cold cache; the service image runs this at build time and
    never again.
    """
    from huggingface_hub import hf_hub_download

    paths: dict[str, Path] = {}
    for filename, expected in MODEL_FILES.items():
        local = Path(
            hf_hub_download(
                MODEL_ID,
                filename,
                revision=MODEL_REVISION,
                cache_dir=str(cache_dir) if cache_dir else None,
            )
        )
        actual = sha256_of(local)
        if actual != expected:
            raise ModelPinError(f"{filename}: sha256 {actual} is not the pinned {expected}")
        paths[filename] = local
    return paths


@dataclass(frozen=True)
class ModelInfo:
    model_id: str
    revision: str
    files: dict[str, str]
    dimension: int
    max_tokens: int


class Embedder:
    """Wraps the ONNX session and the tokenizer. Single-threaded on purpose (see build)."""

    def __init__(self, model_path: Path, tokenizer_path: Path, threads: int = 1) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = threads
        self._session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._input_names = {i.name for i in self._session.get_inputs()}
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(MAX_TOKENS)
        self._tokenizer.no_padding()

    @classmethod
    def pinned(cls, cache_dir: Path | None = None, threads: int = 1) -> Embedder:
        files = fetch_model(cache_dir)
        return cls(files["onnx/model.onnx"], files["onnx/tokenizer.json"], threads)

    @property
    def info(self) -> ModelInfo:
        return ModelInfo(MODEL_ID, MODEL_REVISION, dict(MODEL_FILES), DIMENSION, MAX_TOKENS)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return self._embed([f"passage: {t}" for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([f"query: {text}"])[0]

    def token_count(self, text: str) -> int:
        """Tokens the model would see for a passage, prefix included, before truncation."""
        self._tokenizer.no_truncation()
        try:
            return len(self._tokenizer.encode(f"passage: {text}").ids)
        finally:
            self._tokenizer.enable_truncation(MAX_TOKENS)

    def _embed(self, texts: list[str]) -> np.ndarray:
        out = np.empty((len(texts), DIMENSION), dtype=np.float32)
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            out[start : start + len(batch)] = self._embed_batch(batch)
        return out

    def _embed_batch(self, texts: list[str]) -> np.ndarray:
        encodings = self._tokenizer.encode_batch(texts)
        width = max(len(e.ids) for e in encodings)
        pad_id = self._tokenizer.token_to_id("<pad>")
        ids = np.full((len(texts), width), pad_id, dtype=np.int64)
        mask = np.zeros((len(texts), width), dtype=np.int64)
        for row, e in enumerate(encodings):
            ids[row, : len(e.ids)] = e.ids
            mask[row, : len(e.ids)] = 1
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = np.zeros_like(ids)
        (hidden,) = self._session.run(["last_hidden_state"], feeds)
        # Mean pooling over real tokens, then L2 normalisation — the model card's recipe.
        weights = mask[..., None].astype(np.float32)
        pooled = (hidden * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1e-9)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        return (pooled / np.maximum(norms, 1e-12)).astype(np.float32)
