"""Prompts are versioned artifacts on disk, not strings inside functions.

``prompts/<name>-v<N>.system.md`` is the instructions turn and
``prompts/<name>-v<N>.user.md`` the user turn template. The version is the file
name; the content is part of the recording key, so a changed prompt cannot reuse
a recording made with the old one.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from eclusa.corpus.manifest import Manifest
from eclusa.index.chunks import Chunk

# Repo-relative when running from a checkout; ECLUSA_PROMPTS in the image, where the
# package lives in site-packages and the prompts are copied next to the corpus.
PROMPTS_DIR = Path(
    os.environ.get("ECLUSA_PROMPTS", Path(__file__).resolve().parent.parent.parent / "prompts")
)
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
    """Two header lines, then the passage.

    The act's title goes on its own line and the three fields the model must copy go on
    the next, with ``locator`` last so that it ends at the newline. The first live call
    showed why: the title used to sit in parentheses right after the locator, the prompt
    says to copy the locator exactly, and the model copied "art. 10, caput (Circular nº
    3.978, de 23 de janeiro de 2020)" — right document, right chunk, right answer, and a
    citation the contract could not resolve. The header was ambiguous, so the header is
    what changed; loosening the contract to accept a suffix would have given away the
    guarantee that a citation names a device that exists.
    """
    doc = manifest.by_id(chunk.doc_id)
    locator = chunk.citation or "revogação"
    title = f"[{n}] {doc.title}"
    fields = f"doc_id={chunk.doc_id} chunk_id={chunk.chunk_id} locator={locator}"
    return f"{title}\n{fields}\n{chunk.text}"
