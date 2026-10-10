"""Client for the Banco Central's Busca de Normas endpoint, and the collector's run.

The route: ``exibenormativo`` returns JSON with the act's metadata, its original
wording as HTML (``Texto``) and the list of PDF attachments (``Documentos``);
consolidated versions are PDFs under ``normativos.bcb.gov.br``. Neither is
documented. LexML, which is, sits behind a JavaScript proof-of-work challenge
that a plain HTTP client cannot pass and that this project does not try to.

Politeness is part of the design, not an afterthought: every request carries a
User-Agent naming the project, and requests are spaced out. Twenty-one documents
make the volume irrelevant; the code is public, and a collector without an
interval is a bad example to whoever reads it.

Drift is reported, never overwritten. A document already in the manifest is
re-fetched and compared by hash: a difference is an outcome to look at, and only
an explicit ``--refresh`` replaces the captured bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from eclusa.collector.plan import Plan, Target
from eclusa.corpus.manifest import Document, Manifest, Status, TextSource, VersionKind
from eclusa.ingest.extract import (
    articles,
    extractor_version,
    paragraphs_from_capture,
    paragraphs_from_html,
    save_paragraphs,
)

ENDPOINT = "https://www.bcb.gov.br/api/conteudo/app/normativos/exibenormativo"
ATTACHMENTS = "https://normativos.bcb.gov.br/Lists/Normativos/Attachments"
USER_AGENT = (
    "eclusa-llm-gateway/0.1 (+https://github.com/kabianca/eclusa-llm-gateway; "
    "corpus snapshot refresh; a few requests, spaced out)"
)
COLLECTOR_NOTE = (
    "BCB Busca de Normas endpoint (exibenormativo JSON for metadata and the original "
    "HTML text; normativos.bcb.gov.br attachments for consolidated PDFs). LexML SRU "
    "tried first on 2026-09-14 and blocked by a JavaScript proof-of-work challenge."
)

Fetcher = Callable[[str], bytes]


def polite_fetcher(delay_seconds: float = 2.0, timeout: float = 60.0) -> Fetcher:
    """A fetcher that identifies the project and waits between requests."""
    last_call = [0.0]

    def fetch(url: str) -> bytes:
        wait = last_call[0] + delay_seconds - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read()
        last_call[0] = time.monotonic()
        return body

    return fetch


@dataclass(frozen=True)
class Metadata:
    bcb_id: int
    title: str
    act_date: date
    subject: str
    revoked: bool
    attachments: tuple[str, ...]
    texto: str


def metadata_url(target: Target) -> str:
    query = urllib.parse.urlencode({"p1": target.endpoint_type, "p2": target.number})
    return f"{ENDPOINT}?{query}"


def parse_metadata(payload: bytes) -> Metadata:
    content = json.loads(payload.decode("utf-8"))["conteudo"]
    if not content:
        raise LookupError("the endpoint returned no act for this type and number")
    item = content[0]
    attachments = tuple(
        entry.split(";")[0] for entry in (item.get("Documentos") or "").split("#;") if entry.strip()
    )
    return Metadata(
        bcb_id=int(item["Id"]),
        title=item["Titulo"],
        act_date=date.fromisoformat(item["Data"][:10]),
        subject=re.sub(r"\s+", " ", item["Assunto"]).strip(),
        revoked=bool(item["Revogado"]),
        attachments=attachments,
        texto=item["Texto"] or "",
    )


def choose_attachment(target: Target, attachments: tuple[str, ...]) -> str:
    """The attachment for the planned version, or a LookupError naming what exists."""
    marker = "O" if target.version_kind is VersionKind.ORIGINAL else "L"
    wanted = re.compile(rf"^[A-Za-z_]+_{target.number}_v{target.version_number}_{marker}\.pdf$")
    for name in attachments:
        if wanted.match(name):
            return name
    raise LookupError(f"no attachment for {target.doc_id}; endpoint lists {list(attachments)}")


def newer_consolidations(target: Target, attachments: tuple[str, ...]) -> list[str]:
    """Clean consolidations newer than the planned version: the endpoint moved on."""
    newer = []
    for name in attachments:
        m = re.search(r"_v(\d+)_L\.pdf$", name)
        if m and int(m.group(1)) > target.version_number:
            newer.append(name)
    return sorted(newer)


Action = Literal["captured", "unchanged", "drift", "error"]


@dataclass(frozen=True)
class Outcome:
    doc_id: str
    action: Action
    detail: str = ""
    warnings: tuple[str, ...] = ()


class IncompleteRun(RuntimeError):
    """The run ended with documents that do not form a valid manifest (a dangling
    superseded_by or revoked_by after a failed capture). Nothing is written; the
    per-document outcomes travel with the error so the operator sees what failed."""

    def __init__(self, outcomes: list[Outcome], cause: ValidationError):
        super().__init__(str(cause))
        self.outcomes = outcomes


def collect(
    plan: Plan,
    manifest: Manifest | None,
    corpus_dir: Path,
    fetcher: Fetcher,
    today: date,
    refresh: frozenset[str] = frozenset(),
) -> tuple[Manifest, list[Outcome]]:
    """Capture what the plan lists and the manifest lacks; verify what it has."""
    existing = {d.doc_id: d for d in manifest.documents} if manifest else {}
    documents: list[Document] = []
    outcomes: list[Outcome] = []
    for target in plan.targets:
        try:
            meta = parse_metadata(fetcher(metadata_url(target)))
            warnings = _warnings(target, meta)
            source_url, payload = _payload(target, meta, fetcher)
        except Exception as exc:  # noqa: BLE001 - one bad act must not stop the run
            outcomes.append(Outcome(target.doc_id, "error", f"{type(exc).__name__}: {exc}"))
            if target.doc_id in existing:
                documents.append(existing[target.doc_id])
            continue
        digest = hashlib.sha256(payload).hexdigest()
        previous = existing.get(target.doc_id)
        if previous is not None and target.doc_id not in refresh:
            if previous.sha256 == digest:
                outcomes.append(Outcome(target.doc_id, "unchanged", warnings=warnings))
            else:
                detail = f"downloaded bytes differ from the snapshot; kept {previous.sha256[:12]}"
                outcomes.append(Outcome(target.doc_id, "drift", detail, warnings))
            documents.append(previous)
            continue
        raw = corpus_dir / target.raw_path
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(payload)
        try:
            text_digest = _extract_and_save(target, raw, corpus_dir / target.text_path)
        except Exception as exc:  # noqa: BLE001
            raw.unlink()
            outcomes.append(Outcome(target.doc_id, "error", f"{type(exc).__name__}: {exc}"))
            if previous is not None:
                documents.append(previous)
            continue
        documents.append(
            Document(
                doc_id=target.doc_id,
                act_type=target.act_type,
                number=target.number,
                act_date=target.act_date,
                title=target.title,
                subject=meta.subject,
                version_kind=target.version_kind,
                version_as_of=target.version_as_of,
                status=target.status,
                superseded_by=target.superseded_by,
                revoked_by=target.revoked_by,
                revoked_from=target.revoked_from,
                text_source=target.text_source,
                source_url=source_url,
                bcb_id=meta.bcb_id,
                raw_path=target.raw_path,
                sha256=digest,
                text_path=target.text_path,
                text_sha256=text_digest,
                extractor_version=extractor_version(target.text_source),
                captured_at=today,
            )
        )
        outcomes.append(Outcome(target.doc_id, "captured", f"{len(payload)} bytes", warnings))
    try:
        return Manifest(collector=COLLECTOR_NOTE, documents=tuple(documents)), outcomes
    except ValidationError as exc:
        raise IncompleteRun(outcomes, exc) from exc


def _extract_and_save(target: Target, raw: Path, text_path: Path) -> str:
    """Extract at capture time, so the committed text is the text the capture yields."""
    paragraphs = paragraphs_from_capture(target.text_source, raw, target.designation)
    if not articles(paragraphs):
        raise ValueError("the captured text has no article in it; check the route")
    save_paragraphs(paragraphs, text_path)
    return hashlib.sha256(text_path.read_bytes()).hexdigest()


def reextract(manifest: Manifest, corpus_dir: Path) -> tuple[Manifest, list[Outcome]]:
    """Rebuild every text file from its raw capture, no network. For when the extractor changed.

    The raw files and their hashes are untouched; the text files and their hashes follow the
    extractor. The outcome says which texts changed, so the diff in the corpus is deliberate.
    """
    documents: list[Document] = []
    outcomes: list[Outcome] = []
    for doc in manifest.documents:
        paragraphs = paragraphs_from_capture(
            doc.text_source, corpus_dir / doc.raw_path, doc.designation
        )
        if not articles(paragraphs):
            raise ValueError(f"{doc.doc_id}: re-extraction yields no article; extractor regression")
        text_path = corpus_dir / doc.text_path
        save_paragraphs(paragraphs, text_path)
        digest = hashlib.sha256(text_path.read_bytes()).hexdigest()
        version = extractor_version(doc.text_source)
        if digest == doc.text_sha256 and version == doc.extractor_version:
            outcomes.append(Outcome(doc.doc_id, "unchanged"))
            documents.append(doc)
        else:
            detail = "text re-extracted" if digest != doc.text_sha256 else "extractor version"
            outcomes.append(Outcome(doc.doc_id, "captured", detail))
            documents.append(
                doc.model_copy(update={"text_sha256": digest, "extractor_version": version})
            )
    return Manifest(collector=manifest.collector, documents=tuple(documents)), outcomes


def _warnings(target: Target, meta: Metadata) -> tuple[str, ...]:
    warnings = []
    if meta.act_date != target.act_date:
        warnings.append(f"endpoint dates the act {meta.act_date}, plan says {target.act_date}")
    if meta.revoked != (target.status is Status.REVOKED):
        warnings.append(f"endpoint says revoked={meta.revoked}, plan says status={target.status}")
    # A superseded version is old by design; only the act's current text can be stale.
    newer = newer_consolidations(target, meta.attachments)
    if newer and target.status is not Status.SUPERSEDED:
        warnings.append(f"newer consolidation available: {', '.join(newer)}")
    return tuple(warnings)


def _payload(target: Target, meta: Metadata, fetcher: Fetcher) -> tuple[str, bytes]:
    if target.text_source is TextSource.HTML:
        if target.version_kind is not VersionKind.ORIGINAL:
            raise ValueError("the HTML route only carries the original wording")
        if not paragraphs_from_html(meta.texto):
            raise ValueError("the endpoint's Texto is empty for this act; plan the PDF route")
        return metadata_url(target), meta.texto.encode("utf-8")
    name = choose_attachment(target, meta.attachments)
    url = f"{ATTACHMENTS}/{meta.bcb_id}/{name}"
    payload = fetcher(url)
    if not payload.startswith(b"%PDF"):
        raise ValueError(f"{url} did not return a PDF")
    return url, payload
