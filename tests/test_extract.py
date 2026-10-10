"""Extraction quality, tested before any LLM code exists.

If extraction scrambles article numbering, citations say "art. 12" and the text is
something else; the project dies looking alive. These tests pin, on the real
captured documents, that article numbering is recoverable, monotonic and complete
against hand-checked counts, that page furniture does not survive, that quoted
articles are not headers, and that the two extraction routes agree byte for byte
on articles that did not change between versions.
"""

import re
from pathlib import Path

import pytest

from eclusa.corpus.manifest import Status, TextSource
from eclusa.ingest import extract
from eclusa.ingest.extract import (
    ExtractionError,
    articles,
    footer_pattern,
    load_paragraphs,
    paragraphs_from_html,
    paragraphs_from_pdf,
    paragraphs_of,
)

# Hand-checked against the PDFs on 2026-09-14.
ARTICLES_3978_ORIGINAL = [str(n) for n in range(1, 71)]
ARTICLES_3978_CONSOLIDATED = (
    [str(n) for n in range(1, 24)] + ["23-A"] + [str(n) for n in range(24, 71)]
)
ARTICLES_3461 = [
    *map(str, range(1, 10)), "9-A", "9-B", *map(str, range(10, 16)), "15-A",
    "16", "17", "18", "18-A", "19", "20", "20-A", "21", "22",
]  # fmt: skip
# Provisions of 3.978 that the consolidated text changed (Atualizacoes field of the
# endpoint: Circular 4.005, Resoluções BCB 119, 282 and 344) plus art. 69, where the
# consolidation added a "(Vide Circular nº 3.942...)" note.
CHANGED_IN_3978 = {"16", "18", "24", "28", "33", "68", "69", "70"}


def _label_key(label: str) -> tuple[int, str]:
    number, _, suffix = label.partition("-")
    return int(number), suffix


@pytest.fixture(scope="module")
def v1(manifest, corpus_dir: Path) -> list[str]:
    return paragraphs_of(manifest.by_id("circular-3978-2020@v1"), corpus_dir)


@pytest.fixture(scope="module")
def v5(manifest, corpus_dir: Path) -> list[str]:
    return paragraphs_of(manifest.by_id("circular-3978-2020@v5"), corpus_dir)


@pytest.fixture(scope="module")
def revoked(manifest, corpus_dir: Path) -> list[str]:
    return paragraphs_of(manifest.by_id("circular-3461-2009@v10"), corpus_dir)


@pytest.fixture(scope="module")
def red_flags(manifest, corpus_dir: Path) -> list[str]:
    return paragraphs_of(manifest.by_id("carta-circular-4001-2020@v4"), corpus_dir)


@pytest.fixture(scope="module")
def whole_corpus(manifest, corpus_dir: Path) -> dict[str, list[str]]:
    return {d.doc_id: paragraphs_of(d, corpus_dir) for d in manifest.documents}


# --- numbering is recoverable, complete and monotonic --------------------------------


def test_html_route_recovers_every_article_of_the_original(v1):
    assert list(articles(v1)) == ARTICLES_3978_ORIGINAL


def test_pdf_route_recovers_every_article_of_the_consolidated(v5):
    assert list(articles(v5)) == ARTICLES_3978_CONSOLIDATED


def test_pdf_route_recovers_every_article_of_the_revoked_act(revoked):
    assert list(articles(revoked)) == ARTICLES_3461


def test_red_flag_list_is_two_articles_of_incisos_and_alineas(red_flags):
    body = articles(red_flags)
    assert list(body) == ["1", "2"]
    incisos = [p for p in body["1"] if re.match(r"^[IVXL]+ - ", p)]
    alineas = [p for p in body["1"] if re.match(r"^[a-z]{1,2}\) ", p)]
    assert len(incisos) == 19, "citations into this act must reach inciso level"
    # 161 single-letter alíneas plus aa) to ae): the first count missed the two-letter ones.
    assert len(alineas) == 166
    assert sum(1 for p in alineas if re.match(r"^[a-z]{2}\) ", p)) == 5


@pytest.mark.parametrize("doc", ["v1", "v5", "revoked", "red_flags"])
def test_article_numbering_is_strictly_increasing(doc, request):
    labels = list(articles(request.getfixturevalue(doc)))
    keys = [_label_key(label) for label in labels]
    assert keys == sorted(set(keys)), "an article number repeats or goes backwards"


# --- page furniture and false headers ------------------------------------------------


# --- the whole corpus, not the sample -------------------------------------------------


def test_installed_pdftotext_is_the_version_the_corpus_text_was_extracted_with(manifest):
    # Two poppler majors do not promise the same text for the same PDF. The manifest
    # records the version that produced corpus/text; this environment must match it, or
    # the byte-identity test below would fail for a reason that is not a bug. CI pins
    # poppler-utils=25.03.0-* for the same reason.
    recorded = {d.extractor_version for d in manifest.documents if d.text_source is TextSource.PDF}
    assert len(recorded) == 1, f"corpus text extracted with more than one poppler: {recorded}"
    installed = f"pdftotext {extract.pdftotext_version()}"
    assert installed == recorded.pop(), (
        f"corpus/text was extracted with {recorded or installed!s}; this environment has "
        f"{installed}. Install the pinned poppler (see .github/workflows/tests.yml) or "
        f"re-extract on purpose with `python -m eclusa.collector --reextract`."
    )


def test_html_route_records_that_no_external_tool_was_involved(manifest):
    for d in manifest.documents:
        if d.text_source is TextSource.HTML:
            assert d.extractor_version == extract.HTML_EXTRACTOR, d.doc_id


def test_committed_text_is_exactly_what_the_raw_capture_extracts_to(
    manifest, corpus_dir, whole_corpus
):
    # corpus/text is what the index reads and what reviewers diff; it must never drift
    # from what corpus/raw yields. Same extractor, same poppler: byte-identical.
    installed = extract.pdftotext_version()
    for doc in manifest.documents:
        assert load_paragraphs(corpus_dir / doc.text_path) == whole_corpus[doc.doc_id], (
            f"{doc.doc_id}: committed text differs from re-extraction "
            f"(recorded {doc.extractor_version}, installed pdftotext {installed})"
        )


def test_every_document_yields_articles_in_strictly_increasing_order(whole_corpus):
    for doc_id, paragraphs in whole_corpus.items():
        keys = [_label_key(label) for label in articles(paragraphs)]
        assert keys, f"{doc_id}: no article found"
        assert keys == sorted(set(keys)), f"{doc_id}: numbering repeats or goes backwards"
        assert keys[0] == (1, ""), f"{doc_id}: does not start at art. 1º"


def test_no_footer_survives_in_any_layout(manifest, whole_corpus):
    # Four footer layouts in the corpus: designation + "Página N de M" (3.978, 4.001),
    # designation + bare number (3.461), designation alone (3.517), designation with a
    # full stop (3.583). None may end up as, or inside, a paragraph.
    for doc in manifest.documents:
        if doc.text_source is not TextSource.PDF:
            continue
        footer = footer_pattern(doc.designation)
        loose = re.escape(doc.designation).replace(r"\.", r"\.?")
        inside = re.compile(
            rf"(^|\. |; ){loose},? (de )?\d+ de \w+ de \d{{4}}\.?( \d+| Página \d+ de \d+)?$"
        )
        for p in whole_corpus[doc.doc_id]:
            assert not footer.match(p), f"{doc.doc_id}: footer left as a paragraph: {p!r}"
            assert not inside.search(p), f"{doc.doc_id}: footer joined into a paragraph: {p!r}"
            assert not re.search(r"Página \d+ de \d+", p), f"{doc.doc_id}: {p!r}"


def test_every_revoked_pdf_opens_with_its_revocation(manifest, whole_corpus):
    for doc in manifest.documents:
        if doc.status is Status.REVOKED and doc.text_source is TextSource.PDF:
            head = whole_corpus[doc.doc_id][:3]
            assert any(p.startswith("Documento normativo revogado") for p in head), doc.doc_id
            joined = [p for p in head if p.startswith("CIRCULAR") and "Documento normativo" in p]
            assert joined == [], f"{doc.doc_id}: the revocation header was joined to the title"


def test_a_one_page_document_has_no_footer_and_loses_nothing(manifest, corpus_dir, whole_corpus):
    # Carta Circular 4.037 is one page: no running footer exists, so the footer rule must
    # remove nothing, and the closing matter is still there in the paragraphs.
    doc = manifest.by_id("carta-circular-4037-2020@v1")
    paragraphs = whole_corpus[doc.doc_id]
    assert paragraphs[-1].startswith("Este texto não substitui o publicado no DOU de 29/4/2020")
    assert "Andreia Laís de Melo Silva Vargas" in paragraphs
    assert articles(paragraphs)["2"] == [
        "Art. 2º Esta Carta Circular entra em vigor em 1º de junho de 2020."
    ]
    assert paragraphs_from_pdf(corpus_dir / doc.raw_path) == paragraphs, "nothing to remove"


def test_two_page_documents_keep_a_body_line_that_closes_page_one(whole_corpus):
    # Circular 3.583's first page ends with body text, not a footer; the positional rule
    # must remove only lines that look like this act's footer.
    paragraphs = whole_corpus["circular-3583-2012@v2"]
    joined = " ".join(paragraphs)
    assert "relação de negócio ou dar prosseguimento a relação já existente com o cliente" in joined
    assert not any(p.startswith("Circular nº 3.583, de 12 de março de 2012.") for p in paragraphs)


def test_footer_pattern_accepts_all_four_layouts():
    footer = footer_pattern("Circular nº 3.517")
    assert footer.match("Circular nº 3517, 7 de dezembro de 2010")
    assert footer.match("Circular nº 3.517, de 7 de dezembro de 2010.")
    assert footer.match("Circular nº 3.517, de 7 de dezembro de 2010 3")
    assert footer.match("Circular nº 3.517, de 7 de dezembro de 2010 Página 2 de 2")
    assert footer.match("Página 2 de 2") and footer.match("12")
    assert not footer.match("Circular nº 3.461, de 24 de julho de 2009 1"), "another act's footer"
    assert not footer.match("A Circular nº 3.517 altera o art. 3º."), "body text naming the act"


def test_closing_matter_rule_is_anchored_to_the_last_article():
    # A synthetic act: an unpunctuated line inside art. 1º (a table row, say) is untouched
    # because the rule never looks there; the last article keeps its incisos, even an
    # unpunctuated last one, and loses only the dateline, the signatures and the DOU note.
    paragraphs = [
        "Art. 1º Fica aprovada a tabela.",
        "valores em reais por faixa de renda",
        "§ 1º A tabela vale para todos.",
        "Art. 2º Aplicam-se:",
        "I - o primeiro caso;",
        "II - o segundo caso",
        "Brasília, 24 de julho de 2009.",
        "Alexandre Antonio Tombini Alvir Alberto Hoffmann",
        "Diretor Diretor",
        "Este texto não substitui o publicado no DOU de 27/7/2009, Seção 1, p. 42.",
    ]
    body = articles(paragraphs)
    assert body["1"] == paragraphs[:3]
    assert body["2"] == ["Art. 2º Aplicam-se:", "I - o primeiro caso;", "II - o segundo caso"]
    assert articles(["Art. 1º Sem pontuação final"])["1"] == ["Art. 1º Sem pontuação final"]


def test_closing_matter_is_not_part_of_the_last_article(revoked, red_flags):
    assert articles(revoked)["22"][-1].endswith(".")
    assert not any("Este texto não substitui" in p for p in articles(revoked)["22"])
    assert articles(red_flags)["2"] == [
        "Art. 2º Esta Carta Circular entra em vigor em 1º de outubro de 2020, quando fica revogada "
        "a Carta Circular nº 3.542, de 12 de março de 2012. (Redação dada, a partir de 1º/6/2020, "
        "pela Carta Circular nº 4.037, de 27/4/2020.)"
    ]


def test_quoted_articles_from_other_acts_are_not_headers(v1):
    quoted = [p for p in v1 if p.startswith("“Art.")]
    assert len(quoted) == 3, "art. 68 of the original quotes three articles of Circular 3.691"
    assert quoted[0] in articles(v1)["68"]
    assert list(articles(v1)) == ARTICLES_3978_ORIGINAL


def test_amending_acts_are_made_of_quoted_articles_and_count_only_their_own(whole_corpus):
    # Circular 3.654 quotes "Art. 4º" inside a block opened on a section title
    # ("“Pessoas Expostas Politicamente"), so that article carries no quote mark of its own;
    # it also quotes with a straight double quote ("Art. 10.).
    paragraphs = whole_corpus["circular-3654-2013@v2"]
    assert list(articles(paragraphs)) == ["1", "2", "3"]
    assert any(p.startswith('"Art. 10.') for p in paragraphs)
    assert any(p.startswith("Art. 4º As instituições de que trata") for p in paragraphs)
    # Resolução BCB 282 puts "Art. 1º" alone in its paragraph.
    assert list(articles(whole_corpus["resolucao-bcb-282-2022@v1"])) == ["1", "2", "3"]


def test_html_newlines_inside_a_paragraph_are_whitespace():
    html = "<p>Art. 1º &#160;A Circular passa\na vigorar:</p>\n\n<p>Art. 2º Fim.</p>"
    assert paragraphs_from_html(html) == ["Art. 1º A Circular passa a vigorar:", "Art. 2º Fim."]


def test_revoked_act_carries_its_revocation_in_the_text(revoked):
    assert any(
        p.startswith("Documento normativo revogado, a partir de 1º/10/2020, pela Circular nº 3.978")
        for p in revoked[:3]
    )


# --- the two routes agree, and the version case is visible ---------------------------


def test_unchanged_articles_are_byte_identical_across_routes(v1, v5):
    original, consolidated = articles(v1), articles(v5)
    differing = {label for label in original if original[label] != consolidated.get(label)}
    assert differing == CHANGED_IN_3978
    assert set(consolidated) - set(original) == {"23-A"}


def test_article_70_is_the_version_case(v1, v5):
    assert articles(v1)["70"] == ["Art. 70. Esta Circular entra em vigor em 1º de julho de 2020."]
    (consolidated,) = articles(v5)["70"]
    assert consolidated.startswith(
        "Art. 70. Esta Circular entra em vigor em 1º de outubro de 2020."
    )
    assert "Circular nº 4.005, de 16/4/2020" in consolidated


def test_compound_words_broken_at_the_margin_keep_their_hyphen(v5):
    inciso = next(p for p in articles(v5)["27"] if p.startswith("IV - "))
    assert "Procuradores-Gerais de Justiça" in inciso


# --- a missing extractor fails, it does not skip -------------------------------------


def test_pdf_route_fails_loud_without_pdftotext(monkeypatch, corpus_dir: Path):
    monkeypatch.setattr(extract.shutil, "which", lambda _: None)
    with pytest.raises(ExtractionError, match="pdftotext"):
        paragraphs_from_pdf(corpus_dir / "raw/circular-3978-2020.v5.pdf", "Circular nº 3.978")
    with pytest.raises(ExtractionError, match="pdftotext"):
        extract.pdftotext_version()
