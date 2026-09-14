"""Schema of ``corpus/manifest.json``.

Why a schema rather than a plain list of files: the corpus pins what moves. A
normative act moves in two different ways, and the manifest has to be able to say
both. An act can be *revoked* — a question of document status, answered by a
field and a filter. And an act can exist in several *versions* — the original
text and each consolidation after an amendment — that are almost identical and
differ in one provision. A manifest that cannot express "same act, two versions"
cannot describe Brazilian regulation, and a system that does not model version
answers from the superseded text with total confidence.

So a document is ``act@version`` (``circular-3978-2020@v5``), and a citation is
a document id plus a locator. Every document records its source URL, capture
date and hash: the frozen snapshot is what makes evaluation mean anything.

Two files per document, both hashed, and the version of the tool that turned one
into the other. The raw capture (PDF or the endpoint's HTML) is the provenance;
the extracted text — one normalised paragraph per line — is what the system
actually consumes; ``extractor_version`` says which poppler produced it, because
two poppler majors do not promise the same text for the same PDF. Pin what
moves, and write down what you pinned. Versioning the text extends the audit
trail into the corpus: a diff shows exactly what changed in what the model
reads, and a citation to art. 23-A can be checked by opening a text file rather
than mining a PDF. It also means the serving image never needs a PDF extractor.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

DOC_ID = re.compile(r"^(?P<act>[a-z]+(?:-[a-z]+)*-\d+-\d{4})@(?P<version>v\d+)$")


class ActType(StrEnum):
    CIRCULAR = "Circular"
    CARTA_CIRCULAR = "Carta Circular"
    RESOLUCAO_BCB = "Resolução BCB"
    INSTRUCAO_NORMATIVA_BCB = "Instrução Normativa BCB"


class VersionKind(StrEnum):
    ORIGINAL = "original"
    CONSOLIDATED = "consolidated"


class Status(StrEnum):
    IN_FORCE = "in_force"
    SUPERSEDED = "superseded"  # a later version of the same act replaces this text
    REVOKED = "revoked"  # another act revoked this one; kept so refusals have real text


class TextSource(StrEnum):
    # The BCB endpoint returns the *original* wording as HTML (its Texto field,
    # captured on its own so the hash covers the text and not the volatile
    # metadata around it); consolidated versions exist only as PDF. The rule is:
    # original from HTML when the endpoint has it, consolidated from the latest
    # "_L" (clean) PDF, never "_P" (marked: it duplicates articles).
    HTML = "html"
    PDF = "pdf"


class Document(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str = Field(pattern=DOC_ID.pattern)
    act_type: ActType
    number: int
    act_date: date
    title: str
    subject: str
    version_kind: VersionKind
    version_as_of: date  # date of the last act reflected in this text: amendment or revocation
    status: Status
    superseded_by: str | None = None  # doc_id of the version that replaces this one
    revoked_by: str | None = None  # act_id of the revoking act
    revoked_from: date | None = None
    text_source: TextSource
    source_url: HttpUrl
    bcb_id: int  # the endpoint's own Id, needed to build attachment URLs
    raw_path: str  # relative to the corpus directory: the capture, as downloaded
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    text_path: str  # relative to the corpus directory: extracted text, one paragraph per line
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extractor_version: str  # "pdftotext 25.03.0", or the HTML marker: the text depends on it
    captured_at: date

    @property
    def act_id(self) -> str:
        return DOC_ID.match(self.doc_id)["act"]

    @property
    def designation(self) -> str:
        """How the act names itself, e.g. 'Circular nº 3.978'; running footers start with it."""
        return f"{self.act_type.value} nº {format_number(self.number)}"

    @property
    def version(self) -> str:
        return DOC_ID.match(self.doc_id)["version"]

    @model_validator(mode="after")
    def _fields_agree_with_status(self) -> Document:
        if self.status is Status.IN_FORCE and (self.superseded_by or self.revoked_by):
            raise ValueError(f"{self.doc_id}: in_force documents carry no superseded_by/revoked_by")
        if self.status is Status.SUPERSEDED and not self.superseded_by:
            raise ValueError(f"{self.doc_id}: superseded documents must name superseded_by")
        if self.status is Status.REVOKED and not (self.revoked_by and self.revoked_from):
            raise ValueError(
                f"{self.doc_id}: revoked documents must name revoked_by and revoked_from"
            )
        if self.status is Status.REVOKED and self.superseded_by:
            raise ValueError(
                f"{self.doc_id}: a revoked text is the last version; it is not superseded"
            )
        if self.superseded_by and DOC_ID.match(self.superseded_by or "") is None:
            raise ValueError(f"{self.doc_id}: superseded_by must be a doc_id")
        if self.superseded_by and DOC_ID.match(self.superseded_by)["act"] != self.act_id:
            raise ValueError(f"{self.doc_id}: superseded_by must be a version of the same act")
        return self

    @model_validator(mode="after")
    def _version_dates_agree(self) -> Document:
        if self.version_kind is VersionKind.ORIGINAL and self.version_as_of != self.act_date:
            raise ValueError(f"{self.doc_id}: an original text is as of the act's own date")
        if self.version_kind is VersionKind.CONSOLIDATED and self.version_as_of <= self.act_date:
            raise ValueError(f"{self.doc_id}: a consolidated text is as of a later amending act")
        return self

    @model_validator(mode="after")
    def _source_matches_route(self) -> Document:
        suffix = Path(self.raw_path).suffix
        expected = {TextSource.HTML: ".html", TextSource.PDF: ".pdf"}[self.text_source]
        if suffix != expected:
            raise ValueError(f"{self.doc_id}: text_source {self.text_source} expects {expected}")
        if str(self.source_url).endswith("_P.pdf"):
            raise ValueError(f"{self.doc_id}: never ingest a '_P' (marked) PDF; use '_L'")
        if Path(self.text_path).suffix != ".txt":
            raise ValueError(f"{self.doc_id}: text_path must be a .txt file")
        from_pdftotext = self.extractor_version.startswith("pdftotext ")
        if self.text_source is TextSource.PDF and not from_pdftotext:
            raise ValueError(f"{self.doc_id}: a PDF text must record the pdftotext version")
        if self.text_source is TextSource.HTML and from_pdftotext:
            raise ValueError(f"{self.doc_id}: an HTML text does not come from pdftotext")
        return self


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    collector: str  # how the documents were reached, in one line
    documents: tuple[Document, ...]

    @model_validator(mode="after")
    def _documents_are_consistent(self) -> Manifest:
        ids = [d.doc_id for d in self.documents]
        if len(ids) != len(set(ids)):
            dup = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate doc_id: {dup}")
        by_id = {d.doc_id: d for d in self.documents}
        act_ids = {d.act_id for d in self.documents}
        for d in self.documents:
            if d.superseded_by:
                target = by_id.get(d.superseded_by)
                if target is None:
                    raise ValueError(
                        f"{d.doc_id}: superseded_by {d.superseded_by} is not in the manifest"
                    )
                if target.status is Status.SUPERSEDED:
                    raise ValueError(f"{d.doc_id}: superseded_by must point at the current version")
            if d.revoked_by and d.revoked_by not in act_ids:
                raise ValueError(f"{d.doc_id}: revoking act {d.revoked_by} is not in the manifest")
        for act in sorted(act_ids):
            versions = [d for d in self.documents if d.act_id == act]
            in_force = [d for d in versions if d.status is Status.IN_FORCE]
            if len(in_force) > 1:
                raise ValueError(f"{act}: more than one version in force")
            if in_force and any(d.status is Status.REVOKED for d in versions):
                raise ValueError(f"{act}: an act cannot be both in force and revoked")
        return self

    def by_id(self, doc_id: str) -> Document:
        for d in self.documents:
            if d.doc_id == doc_id:
                return d
        raise KeyError(doc_id)

    def current(self, act_id: str) -> Document | None:
        """The version in force for an act, or None if the act is revoked or unknown."""
        for d in self.documents:
            if d.act_id == act_id and d.status is Status.IN_FORCE:
                return d
        return None

    def versions(self, act_id: str) -> tuple[Document, ...]:
        return tuple(d for d in self.documents if d.act_id == act_id)


def format_number(n: int) -> str:
    """Brazilian thousands separator: 3978 -> '3.978', 119 -> '119'."""
    return f"{n:,}".replace(",", ".")


def load(path: Path) -> Manifest:
    return Manifest.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def hash_mismatches(manifest: Manifest, corpus_dir: Path) -> list[str]:
    """Documents whose raw or text file is missing or differs from the recorded hash.

    Empty means the snapshot on disk is the snapshot the manifest describes.
    """
    problems: list[str] = []
    for d in manifest.documents:
        for rel, expected in ((d.raw_path, d.sha256), (d.text_path, d.text_sha256)):
            path = Path(corpus_dir) / rel
            if not path.is_file():
                problems.append(f"{d.doc_id}: missing {rel}")
            elif sha256_of(path) != expected:
                problems.append(f"{d.doc_id}: sha256 of {rel} differs from the manifest")
    return problems


def act_ids(documents: Iterable[Document]) -> set[str]:
    return {d.act_id for d in documents}
