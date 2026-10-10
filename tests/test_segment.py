"""Locators, validated on the whole corpus.

A citation is a document id plus a locator; if the locator is wrong the citation
points at the wrong law while looking right. So beyond spot checks, the grammar
of Brazilian normative drafting is asserted on every document: incisos run I, II,
III under one parent; alíneas a, b, c (then aa, ab past z); items 1, 2; each
level resets the ones below; quoted blocks and the document's frame carry no
locator of the act's own.
"""

from collections import defaultdict
from pathlib import Path

import pytest

from eclusa.ingest.extract import load_paragraphs
from eclusa.ingest.segment import Locator, Segment, _ordinal, segment

ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50}


def roman(s: str) -> int:
    total = 0
    for i, ch in enumerate(s):
        value = ROMAN[ch]
        total += -value if i + 1 < len(s) and ROMAN[s[i + 1]] > value else value
    return total


def letters(s: str) -> int:
    """a=1 ... z=26, aa=27, ab=28: the alínea sequence past z."""
    n = 0
    for ch in s:
        n = n * 26 + (ord(ch) - ord("a") + 1)
    return n


@pytest.fixture(scope="module")
def segmented(manifest, corpus_dir: Path) -> dict[str, list[Segment]]:
    return {
        d.doc_id: segment(d.doc_id, load_paragraphs(corpus_dir / d.text_path))
        for d in manifest.documents
    }


# --- every paragraph is placed ---------------------------------------------------------


def test_every_paragraph_becomes_exactly_one_segment(manifest, corpus_dir, segmented):
    for d in manifest.documents:
        paragraphs = load_paragraphs(corpus_dir / d.text_path)
        segs = segmented[d.doc_id]
        assert [s.text for s in segs] == paragraphs
        assert [s.index for s in segs] == list(range(len(paragraphs)))


def test_no_paragraph_is_left_as_a_bare_continuation(segmented):
    # A continuation is a paragraph the grammar could not place. On this corpus every
    # paragraph is placed; a new document that breaks this is news, not noise.
    stray = [
        (k, s.citation, s.text[:60])
        for k, v in segmented.items()
        for s in v
        if s.kind == "continuation"
    ]
    assert stray == []


# --- the grammar of devices -------------------------------------------------------------


def test_devices_run_in_sequence_under_their_parent(segmented):
    for doc_id, segs in segmented.items():
        incisos: dict[tuple, list[str]] = defaultdict(list)
        alineas: dict[tuple, list[str]] = defaultdict(list)
        items: dict[tuple, list[str]] = defaultdict(list)
        for s in segs:
            loc = s.locator
            if s.kind == "inciso":
                incisos[(loc.article, loc.paragraph)].append(loc.inciso)
            elif s.kind == "alinea":
                assert loc.inciso is not None, f"{doc_id}: alínea without an inciso: {s.text[:60]}"
                alineas[(loc.article, loc.paragraph, loc.inciso)].append(loc.alinea)
            elif s.kind == "item":
                assert loc.alinea is not None, f"{doc_id}: item without an alínea: {s.text[:60]}"
                items[(loc.article, loc.paragraph, loc.inciso, loc.alinea)].append(loc.item)
        for parent, seq in incisos.items():
            assert [roman(x) for x in seq] == list(range(1, len(seq) + 1)), (doc_id, parent, seq)
        for parent, seq in alineas.items():
            assert [letters(x) for x in seq] == list(range(1, len(seq) + 1)), (doc_id, parent, seq)
        for parent, seq in items.items():
            assert [int(x) for x in seq] == list(range(1, len(seq) + 1)), (doc_id, parent, seq)


def test_paragraphs_of_an_article_are_numbered_or_a_single_unico(segmented):
    for doc_id, segs in segmented.items():
        per_article: dict[str, list[str]] = defaultdict(list)
        for s in segs:
            if s.kind == "paragraph":
                per_article[s.locator.article].append(s.locator.paragraph)
        for article, seq in per_article.items():
            if "único" in seq:
                assert seq == ["único"], (doc_id, article, seq)
            else:
                numbers = [int(p.split("-")[0]) for p in seq]
                assert numbers == sorted(numbers) and numbers[0] == 1, (doc_id, article, seq)


def test_locators_never_point_outside_their_article(segmented):
    for doc_id, segs in segmented.items():
        current = None
        for s in segs:
            if s.kind == "caput":
                current = s.locator.article
            elif s.locator is not None:
                assert s.locator.article == current, (doc_id, s.kind, s.text[:60])


# --- the frame and the quotations carry no locator of the act's own ---------------------


def test_frame_follows_the_last_article_and_has_no_locator(segmented):
    for doc_id, segs in segmented.items():
        kinds = [s.kind for s in segs]
        last_caput = max(i for i, k in enumerate(kinds) if k == "caput")
        frame = [i for i, k in enumerate(kinds) if k in ("closing", "annex")]
        assert frame, f"{doc_id}: no frame at all"
        assert frame[0] > last_caput
        assert frame == list(range(frame[0], len(segs))), f"{doc_id}: frame is not a suffix"
        assert all(segs[i].locator is None for i in frame)


def test_instrucoes_normativas_carry_their_technical_note_as_annex(segmented):
    for doc_id in ("instrucao-normativa-bcb-732-2026@v1", "instrucao-normativa-bcb-761-2026@v1"):
        annex = [s for s in segmented[doc_id] if s.kind == "annex"]
        assert annex and annex[0].text.startswith("NOTA ")
        assert any(s.text.startswith("1. ") for s in annex), (
            "the note's numbered paragraphs are annex"
        )
        assert not any(s.kind == "item" for s in segmented[doc_id]), "not items of the last article"


def test_quoted_blocks_belong_to_the_quoting_article(segmented):
    # Resolução BCB 119 (curly quotes) and Circular 3.517 (straight quotes) are amending
    # acts: everything they quote sits under their own art. 1º and is parsed no further.
    for doc_id in ("resolucao-bcb-119-2021@v1", "circular-3517-2010@v2"):
        segs = segmented[doc_id]
        quoted = [s for s in segs if s.kind == "quoted"]
        assert len(quoted) > 5, doc_id
        assert all(s.locator == Locator(article="1") for s in quoted), doc_id
        frame = ("quoted", "heading", "preamble", "closing", "annex", "revocation_notice")
        own = [s.kind for s in segs if s.kind not in frame]
        assert own == ["caput", "caput"], f"{doc_id}: only its own two articles are devices: {own}"


def test_mixed_quote_marks_do_not_swallow_the_rest_of_the_act(segmented):
    # Circular 3.654 opens a block with a straight quote and closes it with a curly one.
    caputs = [s.locator.article for s in segmented["circular-3654-2013@v2"] if s.kind == "caput"]
    assert caputs == ["1", "2", "3"]


def test_revoked_acts_carry_a_revocation_notice_segment(manifest, segmented):
    for d in manifest.documents:
        notices = [s for s in segmented[d.doc_id] if s.kind == "revocation_notice"]
        expected = d.status.value == "revoked" and d.text_source.value == "pdf"
        assert bool(notices) == expected, d.doc_id


# --- citations read the way a lawyer writes them ----------------------------------------


def test_citation_of_the_deepest_device_in_the_corpus(segmented):
    v5 = segmented["circular-3978-2020@v5"]
    item = next(s for s in v5 if s.kind == "item" and s.text.startswith("2. a administração"))
    assert item.citation == "art. 24, § 3º, VI, g, 2"
    assert item.heading_path == (
        "CAPÍTULO V — DOS PROCEDIMENTOS DESTINADOS A CONHECER OS CLIENTES",
        "Seção VI — Da Identificação e da Qualificação do Beneficiário Final",
    )


def test_citations_of_caput_paragraph_and_inserted_article(segmented):
    v5 = {(s.kind, s.text[:12]): s for s in segmented["circular-3978-2020@v5"]}
    assert v5[("caput", "Art. 1º Esta")].citation == "art. 1º, caput"
    assert v5[("caput", "Art. 70. Est")].citation == "art. 70, caput"
    assert v5[("caput", "Art. 23-A. A")].citation == "art. 23-A, caput"
    unico = next(
        s for s in segmented["circular-3978-2020@v5"] if s.locator == Locator("2", "único")
    )
    assert unico.citation == "art. 2º, parágrafo único"


def test_red_flag_list_reaches_inciso_and_two_letter_alinea(segmented):
    segs = segmented["carta-circular-4001-2020@v4"]
    incisos = [s for s in segs if s.kind == "inciso" and s.locator.article == "1"]
    alineas = [s for s in segs if s.kind == "alinea" and s.locator.article == "1"]
    assert len(incisos) == 19 and incisos[-1].citation == "art. 1º, XIX"
    assert len(alineas) == 166
    assert [s.citation for s in alineas if len(s.locator.alinea) == 2] == [
        f"art. 1º, IV, {a}" for a in ("aa", "ab", "ac", "ad", "ae")
    ]


def test_ordinal_markers_follow_the_convention():
    assert _ordinal("1") == "1º" and _ordinal("9") == "9º" and _ordinal("10") == "10"
    assert _ordinal("9-A") == "9º-A" and _ordinal("23-A") == "23-A"


def test_a_document_without_articles_cannot_be_segmented():
    with pytest.raises(ValueError, match="no article"):
        segment("x", ["Só preâmbulo."])
