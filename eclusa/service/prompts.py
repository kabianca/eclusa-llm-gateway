"""Prompts are versioned artifacts on disk, not strings inside functions.

``prompts/<name>-v<N>.system.md`` is the instructions turn and
``prompts/<name>-v<N>.user.md`` the user turn template. The version is the file
name; the content is part of the recording key, so a changed prompt cannot reuse
a recording made with the old one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from eclusa.corpus.manifest import Manifest
from eclusa.index.chunks import Chunk

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"
VERSIONED = re.compile(r"^(?P<name>[a-z]+)-v(?P<n>\d+)$")


@dataclass(frozen=True)
class Prompt:
    version: str  # "answer-v1"
    system: str
    user_template: str

    @classmethod
    def load(cls, version: str, directory: Path = PROMPTS_DIR) -> Prompt:
        if VERSIONED.match(version) is None:
            raise ValueError(f"prompt version must look like answer-v1, got {version!r}")
        system = (directory / f"{version}.system.md").read_text(encoding="utf-8").strip()
        user = (directory / f"{version}.user.md").read_text(encoding="utf-8").strip()
        return cls(version, system, user)

    def render_user(self, question: str, chunks: list[Chunk], manifest: Manifest) -> str:
        passages = "\n\n".join(_passage(i, c, manifest) for i, c in enumerate(chunks, start=1))
        return self.user_template.format(question=question.strip(), passages=passages)


def _passage(n: int, chunk: Chunk, manifest: Manifest) -> str:
    doc = manifest.by_id(chunk.doc_id)
    locator = chunk.citation or "revogação"
    header = (
        f"[{n}] doc_id={chunk.doc_id} chunk_id={chunk.chunk_id} locator={locator} ({doc.title})"
    )
    return f"{header}\n{chunk.text}"
