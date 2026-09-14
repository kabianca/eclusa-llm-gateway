# Eclusa

### A question enters. What leaves has been checked, charged and written down.

<!-- Draft. Sections still to come, in the house order: Why I built this ·
     Architecture · Running it · Layout · Tests · Where this grows. "Design
     decisions", "What running it taught me" and "What I would do differently"
     are written as things happen. -->

An LLM gateway over the Banco Central do Brasil's normative texts on the
prevention of money laundering and terrorism financing (PLD/FT). A question
enters, the answer is checked against a contract — every statement traceable to
a retrieved passage, or the answer is refused — the budget is debited, the audit
record is written, and only then does the answer leave.

<p>
  <a href="https://github.com/kabianca/eclusa-llm-gateway/actions/workflows/tests.yml">
    <img src="https://github.com/kabianca/eclusa-llm-gateway/actions/workflows/tests.yml/badge.svg" alt="tests">
  </a>
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/license-GPL--3.0-green" alt="GPL-3.0 license">
</p>

The thesis: **an LLM in production is a budget, a contract and an audit trail.
The model is the easy part.** This repository does not claim to prevent
hallucination; that claim is not testable. It claims something narrower and
provable: an answer without a citation that resolves to the frozen corpus is a
refusal, and the corpus and the model are pinned so that an evaluation measures
the pipeline and not whatever moved underneath it.

This is the fifth repository in a series — [Maré](https://github.com/kabianca/bcb-airflow-pipeline),
[Âncora](https://github.com/kabianca/cohort-rfm-ecommerce),
[Estrato](https://github.com/kabianca/estrato-claims-warehouse),
[Foz](https://github.com/kabianca/foz-payments-stream) — that all
argue one discipline: pin what moves, or your measurement measures nothing.
Âncora pins recency to a snapshot date, Estrato replays by `as_of`, Foz fixes
the window with a watermark. Eclusa pins the corpus and the model. Maré reads
what the central bank *measures* (the SGS numeric series API); Eclusa reads what
it *determines* (normative acts, which are not in the open-data portal — a
different service, reached a different way).

## What running it taught me

**An inserted article moved a heading to a different owner — and would have
shifted the version comparison.** The corpus holds Circular 3.978 twice: the
original wording (v1, from the endpoint's HTML) and the current consolidation
(v5, from PDF). A test compares the two article by article and expects the
articles that no amendment touched to come out byte-identical from the two
routes. Art. 23 failed, and its text had not changed. Resolução BCB 344/2023
inserted art. 23-A right after it, at the end of the section, and the section
title that follows — *Da Identificação e da Qualificação do Beneficiário
Final* — was being attached to whichever article came before it: art. 23 in v1,
art. 23-A in v5. The extractor was giving headings to the article above them.
A heading with the wrong owner is a small thing until it lands on the version
comparison, which is the case this project puts in the window: it would have
reported a difference in an article that did not change. Section titles are now
headings in their own right and belong to no article. A test caught it before a
single line of LLM code existed.

**Four footer layouts, and the one-page document that has none.** Each page of
the BCB's PDFs closes with a running footer, and the first version of the
extractor found it by repetition: the line that closes most pages. It passed
on the three sample documents. On the whole corpus it met a 2010 act whose
footer is the title alone (*Circular nº 3517, 7 de dezembro de 2010*, no page
number), a 2012 act whose footer appears only on page two, a 2009 act with a
bare page number, and one-page acts with no footer at all — for which "most
pages" means nothing. Left in place, a footer is glued to the end of whichever
paragraph the page break interrupted, and a citation to that paragraph quotes
the footer as if it were law. The rule is now positional and document-specific:
the last line of a page is a footer if it starts with the act's own
designation, which the manifest knows. Collecting the whole corpus *before*
writing the segmenter is what made this visible; a segmenter validated on three
samples would have shipped the repetition rule.

**Sixty-two of seventy articles identical across two extraction routes — and
the other eight, one by one.** The version comparison only means something if
what differs between v1 and v5 is regulation and not extraction. So the eight
differing articles were classified individually rather than declared "real
change": arts. 16, 18, 24 and 33 changed by Resolução BCB 119/2021; 28 and 68
by Resolução BCB 282/2022; 70 — the entry into force, *julho* to *outubro* —
by Circular 4.005/2020; and 69, whose inciso XVII gained an editorial
cross-reference (*Vide Circular nº 3.942*) in the consolidation. Every change
carries its provenance inline in the consolidated text; none is an artefact of
the HTML-versus-PDF route. The question "when does Circular 3.978 enter into
force?" therefore has a clean answer to demonstrate: the consolidated text says
1º de outubro de 2020, redação dada pela Circular 4.005; the original said 1º
de julho. A system that does not model version answers *julho* with total
confidence. That is the error the corpus is built to catch.

**The documented route exists and is closed.** The plan was to reach the
normative texts through LexML, whose SRU API is documented, before touching the
undocumented endpoint behind the BCB's *Busca de Normas* page. LexML was tried
first. Every request — including `operation=explain`, with a browser
User-Agent — is answered with a Senado Federal security page: a JavaScript
proof-of-work challenge (SHA-256 over `ip;hostname;timestamp;nonce`, difficulty
3, posted to `/_challenge`). Solving it programmatically would mean
circumventing an anti-automation control on a public institution's site, and
circumvention code in a public repository is a poor thing to show anyone
reviewing it. So the collector uses the BCB endpoint, and the README says so:
`exibenormativo` returns the act's metadata, its *original* wording as HTML and
a list of PDF attachments; consolidated versions exist only as those PDFs
(`_L`, clean; `_P`, marked — which duplicates every amended article and is
never ingested). Two acts have an empty HTML text on the endpoint and are
captured from PDF. Every request from the collector names this project in its
User-Agent and waits two seconds; twenty-one documents make the volume
irrelevant, but the code is public and a collector without an interval is a
bad example.

**A hash that would have drifted without the text changing.** The collector
records the SHA-256 of every captured document so that a later refresh detects
drift instead of silently overwriting the snapshot. The first version hashed
the endpoint's whole JSON response for the HTML route. That response carries
`NormasVinculadas` — the list of acts that cite this one — which grows every
time the BCB publishes a new act referring to Circular 3.978, whether or not a
word of the circular changed. The hash would have cried drift at every citation.
What is captured now is the `Texto` field alone, the wording the system
consumes, and the hash covers that. Real change and apparent change are
different things, and telling them apart is what the whole project argues;
this was the smallest place it showed up.

**The act's own web page carries a memo that is not the act.** For Instruções
Normativas, the endpoint's text does not end at the signature. After it comes
*NOTA 388/2026-BCB/DENOR* — the technical note that proposed the act, with its
addressees, its numbered paragraphs 1 to 8 and a second signature block. A walk
that assigns everything after the last article to that article read those
paragraphs as items 1 to 8 of art. 3º. The frame of a document is now found
from its start — the first paragraph after the last article that looks like a
signature, a dateline or a DOU note opens it, and everything after belongs to
it — and the note is kept as an annex: public, useful for "why was this
changed?", never citable as law.

**"Hand-checked" has to mean hand-checked.** The test that pins the shape of
Carta Circular 4.001 asserted 161 alíneas under art. 1º, and I wrote in the
comment that the number was checked by hand. It was not. It came from a regular
expression that matched `a)` to `z)` and stopped; the act continues with `aa)`
to `ae)`. I had verified the code with the code's own output and called it a
check. When the two-letter alíneas surfaced, I asserted they sat under inciso
XVI — from memory, without looking — and the test failed again: they are under
inciso IV. Two unverified claims, both caught by tests written to pin
hand-checked facts, neither of which had been. The test now says 166 and IV,
and the comment above it says how the first number was wrong. A count produced
by the code under test is not a check of the code under test, and a claim made
without opening the document is not a fact — it is exactly the kind of
confident, wrong answer this project exists to refuse.

**The extractor is part of the pipeline, so its version is pinned and written
down.** The committed text must equal what the raw files extract to, byte for
byte — that is what makes the corpus text auditable. GitHub's Ubuntu runner
ships poppler 24.02; the machine the corpus was extracted on ships 25.03. Same
PDF, two poppler majors, no guarantee of the same output. The first fix was to
run the test job inside a Debian image that happens to carry 25.03 — which
makes the test pass while leaving the dependency implicit: nothing in the
repository said which poppler the text needed, and the image tag moves. So the
manifest now records `extractor_version` next to every text hash, the workflow
installs `poppler-utils=25.03.0-*` explicitly, and a test compares the
installed version with the recorded one *before* comparing bytes — so a
mismatch is reported as "corpus/text was extracted with pdftotext 25.03.0; this
environment has 24.02.0", not as an unexplained diff. It is the same discipline
as the frozen corpus and the dated model identifier, one layer down: pin what
moves, and write down what you pinned.

**The version trap has a number.** The first question put to the finished
index was the demonstration case, *"Quando a Circular 3.978 entra em vigor?"*
The top hit was art. 70 of the **original** text — *1º de julho de 2020*, a
date that never came into force — at 0.9145. The consolidated art. 70, the one
that is law, came fourth at 0.9028, because it carries the marker *(Redação
dada, a partir de 1º/6/2020, pela Circular nº 4.005)* and the extra words
dilute the similarity. This is the failure the corpus was built to expose: two
near-identical texts of the same act, and embedding similarity preferring the
superseded one because it is shorter. No flag on the document fixes it;
retrieval has to know what a version is. That layer is the next thing to build,
and this number is what its evaluation will be measured against.

**A near-miss broke the binary.** "Quais procedimentos devem ser adotados na
compra de ouro?" was meant to be a refusal: the act that regulates gold
purchases is outside the corpus. But Carta Circular 4.001 lists red-flag
situations *relacionadas com o mercado de ouro* (inciso XIX, added in 2024), so
retrieval returns something relevant-looking. The honest response is neither
an answer nor a refusal, and the contract as first designed — answer or
refuse — had no place for it. Most RAG systems answer the covered part and say
nothing about the rest, which is the most dangerous way of being wrong,
because it looks complete. So the contract now has three outcomes: *answered*,
*refused*, and *partial* — the system answers what the corpus covers and
declares, in a field of its own, what it does not. Partial has its own value
in the audit trail and its own tests. The gold question is its showcase: *the
corpus covers red-flag situations around the gold market (Carta Circular
4.001, art. 1º, XIX); it does not cover purchase procedures, which are in
Instrução Normativa BCB 406/2023, outside this corpus.* That sentence is more
convincing than any refusal.

## Design decisions

### The embedding model is local, multilingual, fp32 — and 470 MB

Local, because the question has to be embedded at serving time too, and an
embedding API would need a key just to retrieve. Multilingual, because the
corpus is Portuguese legal text and an English-only model degrades silently.
fp32 rather than the 118 MB int8 export, because quantised kernels differ
between CPU feature levels and the same passage would embed differently on
different machines — the reproducibility this project is built on would end at
the first heterogeneous node pool. What that costs: 470 MB fetched once and
verified by hash, and carried in the service image. Locally that is a wait; on
a real cluster it is 470 MB of network and disk per node and a slower pod
start for every replica, which is why the production answer is different (see
below).

### The generation model is the cheapest adequate one, on purpose

The pinned model is `gpt-5.4-mini-2026-03-17` — a dated snapshot, never an
alias, in exactly one place in the code. Not because it is cheap, although it
is. The thesis of this repository is that governance, not model quality, is
what makes an LLM safe in production: the contract that refuses an uncited
statement, the budget that stops before the call, the trail that records what
was blocked. If that layer catches violations from a small model, it is doing
real work. With a frontier model, the model's own quality would mask a weak
contract, and there would be no way to tell the two apart. Choosing the
smallest adequate model is a methodological choice, not an economy.

The honest reversal condition: if, when the evaluation cases are recorded, the
mini produces contract violations on most of them, that is not a reason to
switch quietly. It is a finding, to be written down here first, and only then
a reason to change the model — saying what changed and what the numbers were
before and after.

### The corpus answers what is in force, not the history of changes

Amending acts — Resolução BCB 119, 282, 344, Circular 4.005 — are in the
corpus, but the articles they quote are not indexed: they would duplicate the
consolidated text, which already carries each change's provenance marker, and
compete with it in retrieval. So *"O que a Resolução 344 mudou?"* has no direct
answer in the index, even though the resolution is in the corpus. The markers
in the consolidated text carry part of it — art. 23-A reads *(Incluído pela
Resolução BCB nº 344, de 4/10/2023)* — and that is what such a question gets:
a partial answer that cites the marked provisions and declares that the
amending act's own text, and its full differential effect, are not what this
corpus indexes. The corpus contains the act, not its diff. This is a boundary,
stated here so nobody has to discover it.

### The blocked draft is kept whole, and that costs some privacy

The audit trail stores the question as a hash, not as text. It also stores,
whole, every draft the contract blocked — because "the model tried to say X
and was stopped" is the evidence that the gate worked, and *nothing crosses
unrecorded* has to include what did not cross. The two decisions pull against
each other: a draft is generated from the question and often paraphrases it,
so hashing the question protects less than it appears to. On this corpus that
does not matter — the questions are about public regulation and the evaluation
cases are mine — and the draft is retained on purpose. It is named here so
that nobody has to discover it.

## What I would do differently in production

**Give the blocked draft the same retention policy as the question.** In a
system that answers sensitive questions, hashing the question and keeping the
draft is not a privacy measure; the content comes back through the draft. The
retention policy — how long, who can read it, what is redacted — has to cover
both, or the trail leaks what the hash was meant to hold back.


**Not bake the embedding model into the application image.** 470 MB per
replica pull is fine on a laptop's `kind` and wasteful on a cluster. Two
honest alternatives: an init container that fetches the pinned files once
into a shared volume, so the application image stays small and the model is
pulled per node rather than per replica; or an embedding service of its own,
which also lets the model be pinned and upgraded independently of the
gateway. Both keep the same pin — name, revision, file hashes — that this
repository verifies.

## Licence

GPL-3.0. See [LICENSE](LICENSE).
