"""The manifest is the frozen snapshot's contract: what is on disk is what it says, and
version and revocation are expressible and consistent."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from eclusa.corpus.manifest import Manifest, Status, VersionKind, hash_mismatches


def test_every_raw_and_text_file_is_present_and_matches_its_hash(manifest, corpus_dir: Path):
    assert hash_mismatches(manifest, corpus_dir) == []


def test_a_changed_text_file_is_a_mismatch(manifest, corpus_dir: Path, tmp_path: Path):
    import shutil

    doc = manifest.by_id("circular-3978-2020@v5")
    for rel in (doc.raw_path, doc.text_path):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(corpus_dir / rel, tmp_path / rel)
    only = manifest.model_copy(update={"documents": (doc,)})
    assert hash_mismatches(only, tmp_path) == []
    with open(tmp_path / doc.text_path, "a", encoding="utf-8") as fh:
        fh.write("Art. 71. Um artigo que não existe.\n")
    assert hash_mismatches(only, tmp_path) == [
        f"{doc.doc_id}: sha256 of {doc.text_path} differs from the manifest"
    ]


def test_original_and_consolidated_are_two_documents_of_one_act(manifest):
    v1 = manifest.by_id("circular-3978-2020@v1")
    v5 = manifest.by_id("circular-3978-2020@v5")
    assert v1.act_id == v5.act_id == "circular-3978-2020"
    assert v1.version_kind is VersionKind.ORIGINAL and v1.status is Status.SUPERSEDED
    assert v1.superseded_by == v5.doc_id
    assert v5.version_kind is VersionKind.CONSOLIDATED and v5.status is Status.IN_FORCE
    assert manifest.current("circular-3978-2020") is v5
    assert v1.text_source != v5.text_source, "the two versions arrive by two extraction routes"


def test_revoked_act_names_a_revoking_act_that_is_in_the_corpus(manifest):
    old = manifest.by_id("circular-3461-2009@v10")
    assert old.status is Status.REVOKED
    assert old.revoked_by == "circular-3978-2020"
    assert manifest.current(old.revoked_by) is not None
    assert manifest.current("circular-3461-2009") is None


def test_every_act_has_at_most_one_version_in_force(manifest):
    for act in {d.act_id for d in manifest.documents}:
        in_force = [d for d in manifest.versions(act) if d.status is Status.IN_FORCE]
        assert len(in_force) <= 1, act


# --- what the schema refuses ---------------------------------------------------------


@pytest.fixture
def valid(manifest) -> dict:
    return json.loads(manifest.model_dump_json())


def _doc(payload: dict, doc_id: str) -> dict:
    return next(d for d in payload["documents"] if d["doc_id"] == doc_id)


def test_duplicate_doc_id_is_refused(valid):
    valid["documents"].append(dict(_doc(valid, "circular-3978-2020@v5")))
    with pytest.raises(ValidationError, match="duplicate doc_id"):
        Manifest.model_validate(valid)


def test_superseded_by_must_exist(valid):
    _doc(valid, "circular-3978-2020@v1")["superseded_by"] = "circular-3978-2020@v9"
    with pytest.raises(ValidationError, match="not in the manifest"):
        Manifest.model_validate(valid)


def test_superseded_by_must_be_the_same_act(valid):
    _doc(valid, "circular-3978-2020@v1")["superseded_by"] = "circular-3461-2009@v10"
    with pytest.raises(ValidationError, match="same act"):
        Manifest.model_validate(valid)


def test_two_versions_in_force_are_refused(valid):
    v1 = _doc(valid, "circular-3978-2020@v1")
    v1.update(status="in_force", superseded_by=None)
    with pytest.raises(ValidationError, match="more than one version in force"):
        Manifest.model_validate(valid)


def test_revoking_act_must_be_in_the_corpus(valid):
    _doc(valid, "circular-3461-2009@v10")["revoked_by"] = "resolucao-bcb-9999-2099"
    with pytest.raises(ValidationError, match="not in the manifest"):
        Manifest.model_validate(valid)


def test_revoked_without_date_is_refused(valid):
    _doc(valid, "circular-3461-2009@v10")["revoked_from"] = None
    with pytest.raises(ValidationError, match="revoked_by and revoked_from"):
        Manifest.model_validate(valid)


def test_original_text_is_dated_by_the_act_itself(valid):
    _doc(valid, "circular-3978-2020@v1")["version_as_of"] = "2021-01-01"
    with pytest.raises(ValidationError, match="act's own date"):
        Manifest.model_validate(valid)


def test_marked_pdf_is_never_a_source(valid):
    doc = _doc(valid, "circular-3978-2020@v5")
    doc["source_url"] = doc["source_url"].replace("_L.pdf", "_P.pdf")
    with pytest.raises(ValidationError, match="never ingest"):
        Manifest.model_validate(valid)


def test_pdf_text_must_record_its_pdftotext(valid):
    _doc(valid, "circular-3978-2020@v5")["extractor_version"] = "html (no external tool)"
    with pytest.raises(ValidationError, match="record the pdftotext version"):
        Manifest.model_validate(valid)
    _doc(valid, "circular-3978-2020@v1")["extractor_version"] = "pdftotext 25.03.0"
    with pytest.raises(ValidationError, match="does not come from pdftotext"):
        Manifest.model_validate(valid)


def test_text_route_must_match_the_raw_file(valid):
    _doc(valid, "circular-3978-2020@v1")["text_source"] = "pdf"  # but the raw file is .html
    with pytest.raises(ValidationError, match="expects .pdf"):
        Manifest.model_validate(valid)
