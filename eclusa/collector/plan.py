"""What the corpus should contain, before anything is fetched.

The plan is hand-curated: which acts, which version of each, and what the
manifest should say about status and revocation. Those facts are legal
judgements about the boundary of the corpus, not something to scrape. The
collector turns a plan entry into a manifest entry by fetching the endpoint's
metadata and the document bytes, and by hashing what it got.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eclusa.corpus.manifest import DOC_ID, ActType, Status, TextSource, VersionKind, format_number

MONTHS_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]  # fmt: skip


class Target(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str = Field(pattern=DOC_ID.pattern)
    act_type: ActType
    number: int
    act_date: date
    version_kind: VersionKind
    version_as_of: date
    status: Status
    superseded_by: str | None = None
    revoked_by: str | None = None
    revoked_from: date | None = None
    text_source: TextSource

    @property
    def act_id(self) -> str:
        return DOC_ID.match(self.doc_id)["act"]

    @property
    def version_number(self) -> int:
        return int(DOC_ID.match(self.doc_id)["version"][1:])

    @property
    def endpoint_type(self) -> str:
        """The endpoint's ``p1`` parameter is the act type in upper case."""
        return self.act_type.value.upper()

    @property
    def title(self) -> str:
        number, when = format_number(self.number), format_date_pt(self.act_date)
        return f"{self.act_type.value} nº {number}, de {when}"

    @property
    def raw_path(self) -> str:
        suffix = {TextSource.HTML: "html", TextSource.PDF: "pdf"}[self.text_source]
        return f"raw/{self.act_id}.v{self.version_number}.{suffix}"

    @property
    def text_path(self) -> str:
        return f"text/{self.act_id}.v{self.version_number}.txt"

    @property
    def designation(self) -> str:
        return f"{self.act_type.value} nº {format_number(self.number)}"

    @model_validator(mode="after")
    def _html_route_is_only_for_originals(self) -> Target:
        # The endpoint's Texto is the original wording; consolidated text exists only as PDF.
        if self.text_source is TextSource.HTML and self.version_kind is not VersionKind.ORIGINAL:
            raise ValueError(f"{self.doc_id}: the HTML route only carries the original wording")
        return self


class Plan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    targets: tuple[Target, ...]

    @model_validator(mode="after")
    def _unique_ids(self) -> Plan:
        ids = [t.doc_id for t in self.targets]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate doc_id in plan")
        return self


def load(path: Path) -> Plan:
    return Plan.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def format_date_pt(d: date) -> str:
    day = "1º" if d.day == 1 else str(d.day)
    return f"{day} de {MONTHS_PT[d.month - 1]} de {d.year}"
