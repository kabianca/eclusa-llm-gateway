"""The collector, without the network: a fake fetcher plays the endpoint.

What matters here is not that HTTP works but that the run is honest: it captures
what is missing, re-verifies what it has by hash, reports drift instead of
overwriting it, refuses a text route that yields nothing, and only replaces bytes
when told to.
"""

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from eclusa.collector import bcb
from eclusa.collector import plan as plan_mod
from eclusa.collector.bcb import (
    ATTACHMENTS,
    USER_AGENT,
    IncompleteRun,
    choose_attachment,
    collect,
    metadata_url,
    newer_consolidations,
)
from eclusa.collector.plan import Plan, Target, format_date_pt
from eclusa.corpus.manifest import Status, TextSource, format_number, hash_mismatches
from eclusa.ingest.extract import load_paragraphs, paragraphs_from_html_file

TEXTO = "<div><p>Art. 1º Texto.</p><p>Art. 2º Esta Circular entra em vigor.</p></div>"
PDF = b"%PDF-1.7 fake consolidated text"


def endpoint_payload(*, attachments: str = "", revogado: bool = False, texto: str = TEXTO) -> bytes:
    return json.dumps(
        {
            "conteudo": [
                {
                    "Id": 50905,
                    "Titulo": "Circular N° 3.978",
                    "Data": "2020-01-23T13:30:00Z",
                    "Assunto": "  Dispõe sobre   a política.  ",
                    "Revogado": revogado,
                    "Documentos": attachments,
                    "Texto": texto,
                }
            ]
        }
    ).encode("utf-8")


@pytest.fixture(autouse=True)
def fake_pdf_extraction(monkeypatch):
    """The fake PDFs are not PDFs; extraction of that route is stubbed, HTML stays real."""

    def extract(route, raw, designation):
        if route is TextSource.PDF:
            return ["Art. 1º Texto consolidado.", "Art. 2º Fim."]
        return paragraphs_from_html_file(raw)

    monkeypatch.setattr(bcb, "paragraphs_from_capture", extract)
    monkeypatch.setattr(
        bcb,
        "extractor_version",
        lambda route: (
            "pdftotext 0.0.0-test" if route is TextSource.PDF else "html (no external tool)"
        ),
    )


class FakeFetcher:
    def __init__(self, responses: dict[str, bytes]):
        self.responses = responses
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        return self.responses[url]


def target(**overrides) -> Target:
    base = dict(
        doc_id="circular-3978-2020@v5",
        act_type="Circular",
        number=3978,
        act_date="2020-01-23",
        version_kind="consolidated",
        version_as_of="2023-10-04",
        status="in_force",
        text_source="pdf",
    )
    base.update(overrides)
    return Target.model_validate(base)


V5 = target()
V1 = target(
    doc_id="circular-3978-2020@v1",
    version_kind="original",
    version_as_of="2020-01-23",
    status="superseded",
    superseded_by="circular-3978-2020@v5",
    text_source="html",
)
ATTACH = "Circ_3978_v1_O.pdf;705#;Circ_3978_v5_L.pdf;291#;Circ_3978_v5_P.pdf;297#;"
PDF_URL = f"{ATTACHMENTS}/50905/Circ_3978_v5_L.pdf"


def responses(**kwargs) -> dict[str, bytes]:
    return {metadata_url(V5): endpoint_payload(attachments=ATTACH, **kwargs), PDF_URL: PDF}


# --- plan ------------------------------------------------------------------------


def test_the_committed_plan_is_valid_and_consistent_with_the_manifest(corpus_dir: Path, manifest):
    plan = plan_mod.load(corpus_dir / "plan.json")
    planned = {t.doc_id: t for t in plan.targets}
    for doc in manifest.documents:
        assert doc.doc_id in planned, "every captured document is planned"
        assert doc.raw_path == planned[doc.doc_id].raw_path
        assert doc.status is planned[doc.doc_id].status


def test_html_route_is_refused_for_consolidated_text():
    with pytest.raises(ValidationError, match="HTML route only carries the original"):
        target(text_source="html")


def test_titles_follow_the_official_form():
    assert V5.title == "Circular nº 3.978, de 23 de janeiro de 2020"
    assert format_number(119) == "119"
    assert format_date_pt(date(2020, 10, 1)) == "1º de outubro de 2020"
    assert V5.endpoint_type == "CIRCULAR"
    assert target(act_type="Resolução BCB", number=44).endpoint_type == "RESOLUÇÃO BCB"


def test_attachment_choice_follows_version_and_kind():
    attachments = ("Circ_3978_v1_O.pdf", "Circ_3978_v5_L.pdf", "Circ_3978_v5_P.pdf")
    assert choose_attachment(V5, attachments) == "Circ_3978_v5_L.pdf"
    assert choose_attachment(V1, attachments) == "Circ_3978_v1_O.pdf"
    with pytest.raises(LookupError, match="no attachment"):
        choose_attachment(target(doc_id="circular-3978-2020@v6"), attachments)
    assert newer_consolidations(V5, attachments + ("Circ_3978_v6_L.pdf",)) == ["Circ_3978_v6_L.pdf"]


# --- the run ------------------------------------------------------------------------


def test_first_run_captures_and_hashes_the_downloaded_bytes(tmp_path: Path):
    fetcher = FakeFetcher(responses())
    manifest, outcomes = collect(Plan(targets=(V5,)), None, tmp_path, fetcher, date(2026, 9, 14))
    assert [o.action for o in outcomes] == ["captured"]
    (doc,) = manifest.documents
    assert (tmp_path / doc.raw_path).read_bytes() == PDF
    assert load_paragraphs(tmp_path / doc.text_path) == [
        "Art. 1º Texto consolidado.",
        "Art. 2º Fim.",
    ]
    assert hash_mismatches(manifest, tmp_path) == [], "raw and text are both hashed"
    assert doc.extractor_version == "pdftotext 0.0.0-test", "the extractor is recorded too"
    assert doc.subject == "Dispõe sobre a política."
    assert str(doc.source_url) == PDF_URL
    assert doc.captured_at == date(2026, 9, 14)


def test_second_run_verifies_by_hash_and_reports_drift_without_overwriting(tmp_path: Path):
    manifest, _ = collect(
        Plan(targets=(V5,)), None, tmp_path, FakeFetcher(responses()), date(2026, 9, 14)
    )

    same = FakeFetcher(responses())
    again, outcomes = collect(Plan(targets=(V5,)), manifest, tmp_path, same, date(2026, 12, 1))
    assert [o.action for o in outcomes] == ["unchanged"]
    assert again.documents == manifest.documents

    drifted = FakeFetcher({**responses(), PDF_URL: b"%PDF-1.7 something changed upstream"})
    kept, outcomes = collect(Plan(targets=(V5,)), manifest, tmp_path, drifted, date(2026, 12, 1))
    assert [o.action for o in outcomes] == ["drift"]
    assert kept.documents == manifest.documents, "the snapshot is not touched"
    assert (tmp_path / "raw/circular-3978-2020.v5.pdf").read_bytes() == PDF
    assert hash_mismatches(kept, tmp_path) == []


def test_refresh_is_the_only_way_to_replace_captured_bytes(tmp_path: Path):
    manifest, _ = collect(
        Plan(targets=(V5,)), None, tmp_path, FakeFetcher(responses()), date(2026, 9, 14)
    )
    new_pdf = b"%PDF-1.7 refreshed on purpose"
    fetcher = FakeFetcher({**responses(), PDF_URL: new_pdf})
    refreshed, outcomes = collect(
        Plan(targets=(V5,)), manifest, tmp_path, fetcher, date(2026, 12, 1), frozenset({V5.doc_id})
    )
    assert [o.action for o in outcomes] == ["captured"]
    assert (tmp_path / "raw/circular-3978-2020.v5.pdf").read_bytes() == new_pdf
    assert refreshed.documents[0].captured_at == date(2026, 12, 1)
    assert hash_mismatches(refreshed, tmp_path) == []


def test_html_route_captures_the_texto_field_only(tmp_path: Path):
    fetcher = FakeFetcher(responses())  # the same endpoint payload serves both versions
    manifest, outcomes = collect(Plan(targets=(V1, V5)), None, tmp_path, fetcher, date(2026, 9, 14))
    assert [o.action for o in outcomes] == ["captured", "captured"]
    assert (tmp_path / "raw/circular-3978-2020.v1.html").read_text(encoding="utf-8") == TEXTO
    assert str(manifest.by_id(V1.doc_id).source_url) == metadata_url(V1)
    assert fetcher.calls.count(PDF_URL) == 1, "the HTML route downloads no attachment"


def test_a_run_that_cannot_form_a_valid_manifest_writes_nothing(tmp_path: Path):
    # V5 fails, so V1's superseded_by would dangle: the run must not produce a manifest.
    fetcher = FakeFetcher({metadata_url(V1): endpoint_payload(attachments="")})
    with pytest.raises(IncompleteRun) as info:
        collect(Plan(targets=(V1, V5)), None, tmp_path, fetcher, date(2026, 9, 14))
    assert [o.action for o in info.value.outcomes] == ["captured", "error"]


def test_a_capture_without_articles_is_an_error_and_leaves_no_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(bcb, "paragraphs_from_capture", lambda *_: ["Só preâmbulo, sem artigo."])
    manifest, outcomes = collect(
        Plan(targets=(V5,)), None, tmp_path, FakeFetcher(responses()), date(2026, 9, 14)
    )
    assert outcomes[0].action == "error" and "no article" in outcomes[0].detail
    assert not (tmp_path / V5.raw_path).exists(), "a failed capture leaves no raw file behind"
    assert manifest.documents == ()


def test_an_empty_texto_is_an_error_not_an_empty_document(tmp_path: Path):
    empty = '<div class="ExternalClass"><p>​</p></div>'
    fetcher = FakeFetcher({metadata_url(V1): endpoint_payload(texto=empty)})
    manifest, outcomes = collect(Plan(targets=(V1,)), None, tmp_path, fetcher, date(2026, 9, 14))
    assert outcomes[0].action == "error"
    assert "plan the PDF route" in outcomes[0].detail
    assert manifest.documents == ()


def test_disagreement_with_the_endpoint_is_a_warning_on_the_outcome(tmp_path: Path):
    fetcher = FakeFetcher(responses(revogado=True))
    _, outcomes = collect(Plan(targets=(V5,)), None, tmp_path, fetcher, date(2026, 9, 14))
    assert outcomes[0].action == "captured"
    assert any("revoked=True" in w for w in outcomes[0].warnings)


def test_a_superseded_original_is_not_warned_about_newer_consolidations(tmp_path: Path):
    fetcher = FakeFetcher(responses())
    _, outcomes = collect(Plan(targets=(V1, V5)), None, tmp_path, fetcher, date(2026, 9, 14))
    assert outcomes[0].warnings == (), "v1 is superseded on purpose; v2..v5 existing is not news"
    stale = target(doc_id="circular-3978-2020@v4", version_as_of="2022-12-31")
    listing = "Circ_3978_v1_O.pdf;705#;Circ_3978_v4_L.pdf;280#;Circ_3978_v5_L.pdf;291#;"
    fetcher = FakeFetcher(
        {
            metadata_url(stale): endpoint_payload(attachments=listing),
            f"{ATTACHMENTS}/50905/Circ_3978_v4_L.pdf": PDF,
        }
    )
    _, outcomes = collect(Plan(targets=(stale,)), None, tmp_path, fetcher, date(2026, 9, 14))
    assert outcomes[0].action == "captured"
    assert any("Circ_3978_v5_L.pdf" in w for w in outcomes[0].warnings)


def test_a_failing_act_keeps_its_previous_capture(tmp_path: Path):
    manifest, _ = collect(
        Plan(targets=(V5,)), None, tmp_path, FakeFetcher(responses()), date(2026, 9, 14)
    )
    broken = FakeFetcher({metadata_url(V5): b'{"conteudo": []}'})
    kept, outcomes = collect(Plan(targets=(V5,)), manifest, tmp_path, broken, date(2026, 12, 1))
    assert outcomes[0].action == "error"
    assert kept.documents == manifest.documents


def test_the_user_agent_names_the_project():
    assert "eclusa-llm-gateway" in USER_AGENT
    assert "github.com/kabianca/eclusa-llm-gateway" in USER_AGENT


def test_target_status_is_a_status(tmp_path: Path):
    assert V1.status is Status.SUPERSEDED
