# Eclusa

### A question enters. What leaves has been checked, charged and written down.

An LLM gateway over the Banco Central do Brasil's normative texts on the
prevention of money laundering and terrorism financing (PLD/FT). A question
enters, the answer is checked against a contract — every statement traceable to
a retrieved passage, or the answer is refused: the budget is debited, the audit
record is written, and only then does the answer leave.

<p>
  <a href="https://github.com/kabianca/eclusa-llm-gateway/actions/workflows/tests.yml">
    <img src="https://github.com/kabianca/eclusa-llm-gateway/actions/workflows/tests.yml/badge.svg" alt="tests">
  </a>
  <a href="https://github.com/kabianca/eclusa-llm-gateway/actions/workflows/kind.yml">
    <img src="https://github.com/kabianca/eclusa-llm-gateway/actions/workflows/kind.yml/badge.svg" alt="kind">
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

## Why I built this

Every demonstration of retrieval-augmented generation I had read measured the
model. None of them measured the things that decide whether the answer can be
trusted: whether the citation resolves, whether the corpus moved under the
evaluation, what the call cost, and what was recorded when the answer was
refused. Those are the parts an auditor asks about, and they are the parts
that are missing.

So the subject is one I can judge — the Banco Central's PLD/FT rules — and the
corpus is frozen, because a corpus that changes underneath the system makes
evaluation meaningless: a regression could be the prompt, or it could be a
revoked norm, and there is no way to tell. The same act is held in two
versions on purpose. Asked when Circular 3.978 came into force, a system that
does not model version answers *1º de julho de 2020* with total confidence —
a date that never came into force, because Circular 4.005 moved it to
October. That error is not hypothetical; it is what a compliance analyst does
every week when a search lands them on the original PDF.

## Architecture

```
corpus/      21 normative acts, frozen: the capture, the extracted text, and
             for each one its source URL, capture date, hash and the version of
             the extractor that produced it
collector/   the optional refresh path: polite, hash-checked, reports drift
             instead of overwriting it. Never needed to run the service
ingest/      two extraction routes reduced to one form, then segmentation that
             gives every paragraph a locator: art. 24, § 3º, VI, g, 2
index/       chunking into units, notices and amendments; a local multilingual
             embedding model pinned by revision and file hash; exact search
service/     the lock: contract -> budget -> provider -> audit, behind HTTP
eval/        retrieval and generation measured separately, both frozen first
k8s/         manifests and the kind config CI applies them to
```

The cycle, for one question:

```
question
  -> retrieve        version-aware: text in force first, history only where it
                     differs, a revoked act's notice attached by rule
  -> budget          the ceiling buys a number of output tokens; if what is
                     left buys too few, the call is never made
  -> provider        recordings by default; the live model only with a flag
                     and a key, both set deliberately
  -> contract        every statement cites a passage retrieved for *this*
                     request, at a locator that exists inside it; superseded
                     text needs the current version, revoked text needs its
                     revocation
  -> audit           one record, appended, including the drafts that were
                     blocked and what they tried to say
answer, or a refusal that says why
```

## What running it taught me

**An inserted article moved a heading to a different owner, and would have
shifted the version comparison.** The corpus holds Circular 3.978 twice: the
original wording (v1, from the endpoint's HTML) and the current consolidation
(v5, from PDF). A test compares the two article by article and expects the
articles that no amendment touched to come out byte-identical from the two
routes. Art. 23 failed, and its text had not changed. Resolução BCB 344/2023
inserted art. 23-A right after it, at the end of the section, and the section
title that follows (*Da Identificação e da Qualificação do Beneficiário
Final*) was being attached to whichever article came before it: art. 23 in v1,
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

**Sixty-two of seventy articles identical across two extraction routes, and
the other eight, one by one.** The version comparison only means something if
what differs between v1 and v5 is regulation and not extraction. So the eight
differing articles were classified individually rather than declared "real
change": arts. 16, 18, 24 and 33 changed by Resolução BCB 119/2021; 28 and 68
by Resolução BCB 282/2022; 70 (the entry into force, *julho* to *outubro* —
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

**A boundary in this README was not a boundary; it was a decision of mine.**
This file used to state, as a property of the corpus, that it answers what is
in force and not the history of changes: that *"O que a Resolução BCB 344
mudou?"* had no answer, that the corpus contains the act and not its diff. It
was written with conviction and it was wrong. Resolução 344's art. 1º is
followed, in the corpus, by the full text it gave to art. 23-A, closing with
*(NR)* — the act states its own effect exhaustively. What had no answer was the
**index**, because the chunker dropped every block an amending act
transcribes — ten per cent of the corpus, 183 of 1,873 paragraphs — on the
reasonable grounds that they duplicate consolidated text and would compete
with it in retrieval. The competition is real; discarding a tenth of the corpus
was not the only way to avoid it. It took a reader saying "look at the eight
lines after the passage you quoted" to see it. Those blocks are indexed now, as
their own kind of chunk, demoted below text in force unless the question names
the amending act — the rule the revocation notice already used. On the frozen
set the new metric went 0 → 100%, nothing regressed, and the mean reciprocal
rank of in-force provisions rose 0.80 → 0.85, because one case — does Circular
3.978 amend the FX circular? — had been ranking on a caput whose content was
being thrown away. The lesson is not about chunking. A limitation worth putting
in a README is worth checking against the corpus first, or you publish your own
implementation choice as a fact about the world.

**The version trap has a number.** The first question put to the finished
index was the demonstration case, *"Quando a Circular 3.978 entra em vigor?"*
The top hit was art. 70 of the **original** text — *1º de julho de 2020*, a
date that never came into force — at 0.9145. The consolidated art. 70, the one
that is law, came fourth at 0.9028, because it carries the marker *(Redação
dada, a partir de 1º/6/2020, pela Circular nº 4.005)* and the extra words
dilute the similarity. This is the failure the corpus was built to expose: two
near-identical texts of the same act, and embedding similarity preferring the
superseded one because it is shorter. No flag on the document fixes it;
retrieval has to know what a version is.

The pair of numbers, then — because a number alone reads as an unsolved
problem. Before touching retrieval, twenty-four version-sensitive questions
and five metrics were written and frozen (`eval/retrieval/METRIC.md`), so that
the fix could not be tuned to its own test. On that set, the raw index found
the expected provision in 92% of the cases but ranked the version in force
first in **25%** — and in **0%** of the provisions whose wording never
changed, because identical texts tie and the tie-break by chunk id picked
`@v1` before `@v5` alphabetically. A tie is a decision; that one was wrong. The
version-aware layer changes no score: it groups chunks by act and unit, puts
the version in force first, keeps the original only where its wording differs,
ranks revoked acts below acts in force unless the question names them, and
attaches the revocation notice by rule. On the same frozen set: in-force
first **100%**, mean reciprocal rank of the in-force provision 0.38 → 0.80,
revoked below current 60% → 100%, revocation notice present 0% → 100%. The
provision was found in the same 92% — the layer cannot find what the
embeddings miss, and does not pretend to.

Three of those numbers went to 100% because the layer guarantees the property
by construction — the version in force comes from the index by rule, the
notice is attached by rule. They measure that the rule was applied, not that
the rule is right: they are regression guards, and they are reported as such.
The number that measures retrieval is the one that did not move. And a rule
is only tested where it fires unless the set also holds the cases where it
must not: two questions that name the revoked act, where forcing the text in
force first would be wrong, and two that ask about the original wording,
where dropping it would be — added by documented amendment to the frozen set,
and passing before and after, which is what shows the rules have an exception
that works.

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

### Who says an answer is right: a person, once

Recording the model's answers gives outputs; saying whether an output is right
needs a grader, and there were two bad options and one good one. An LLM judge
adds a second non-deterministic component to a project whose thesis is
determinism. A rule-based grader reaches form — outcome, citations, key
phrases — but not content. So the author grades by hand, once: fifteen
questions, a domain she can judge, and the verdicts committed next to the
recorded answers (`eval/generation/`). From then on the evaluation is a
regression test — recorded response plus committed grade — with no judge and
no network. The expectations were written from the corpus text before the
live run, so the recording could not shape what it was measured against; the
grades are written after, on content the code cannot judge. A `fail` grade is
kept and reported, not hidden: it is what the reversal condition on the
generation model is measured against.

### Three kinds of passage, because the corpus holds three

A chunk is a *unit* of the law — a caput or a § with what nests under it. Two
kinds of passage are not that, and each gets its own.

A revoked act's **revocation notice** is a chunk of its own, because it is the
passage an answer about a revoked act has to cite and no question ever
resembles it; retrieval attaches it by rule rather than by similarity.

An amending act's article, carrying **the text it transcribes**, is the third:
*"Art. 1º A Circular nº 3.978 … passa a vigorar com as seguintes alterações:
«Art. 23-A …»"*. Those transcriptions duplicate consolidated text that already
carries its own provenance marker, so the obvious move is to drop them, and for
a while I did — which is how *"O que a Resolução 344 mudou?"* came to have no
answer in a corpus that answers it verbatim. They are indexed now, always
joined to the article that transcribes them so they can never pass for the law
itself, and ranked below text in force unless the question names the amending
act. The header of such a passage says what it is, and the prompt forbids
citing it as the wording in force.

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

## Running it

Everything but the cluster is `make`, and nothing here reaches a paid API.

```bash
make test        # the gate: 143 tests, no network to any model, no key
make lint        # ruff
make index       # embed the corpus into var/index (a few minutes the first time:
                 # it downloads the pinned embedding model, ~470 MB, once)
make eval        # retrieval over the frozen cases, and the generation gate
```

A question, without the cluster:

```bash
.venv/bin/python -m eclusa.index search "Quando a Circular 3.978 entra em vigor?"
.venv/bin/uvicorn eclusa.service.app:app --port 8000
curl -s localhost:8000/readyz | python3 -m json.tool
```

### Proving it on a cluster

```bash
make prove       # kind up, build, load, apply, wait for readiness, ask a question
```

`make prove` creates a `kind` cluster, builds the image, loads it with `kind
load docker-image` — it never comes from a registry — applies the manifests,
waits for the rollout, and then asks the service a real question and checks the
answer: the outcome, a statement, and a citation naming a document and a
device. The pod does that **with no network and no API key**, because the
provider replays the committed recordings unless told twice to go live. The
same sequence runs in CI on every push, which is the difference between
knowing Kubernetes and showing it running.

```bash
make kind-down   # when you are done
```

The live model is reached only by `make record`, which needs `ECLUSA_LIVE=1`
and `OPENAI_API_KEY` in the environment and stops before any call that would
push the run's worst case over a ceiling. Recording the fifteen evaluation
cases costs about five cents.

## Layout

```
corpus/        manifest.json + raw/ (as captured) + text/ (what the system reads)
collector/     eclusa/collector: the refresh path for the corpus
eclusa/ingest  extraction (two routes, one form) and segmentation with locators
eclusa/index   chunking, the pinned embedding model, exact search, version-aware
               retrieval
eclusa/service contract, budget, audit, provider, prompts, the gateway, the app
eclusa/eval    the two evaluations
prompts/       versioned prompt artifacts on disk, not strings inside functions
eval/          frozen cases, metrics, measurements and the recorded answers
k8s/           manifests + the kind cluster config
tests/         143 tests
```

## Tests

The gate is deterministic and offline. `pytest` with no arguments cannot call a
paid API: the provider that replays recordings is the default, the live client
is imported only when `ECLUSA_LIVE=1` and a key are both set, and a test asserts
that the OpenAI SDK is not even loaded in recorded mode. If `pytest` alone could
spend money, the design would be wrong, not the permission.

What the suite holds, beyond the usual:

- **Extraction**, before any LLM code existed: article numbering recoverable,
  monotonic and complete against hand-checked counts, in four footer layouts;
  the committed text byte-identical to what the raw captures extract to, with
  the poppler version asserted first so a mismatch is named rather than left as
  an unexplained diff.
- **The manifest**: what the schema refuses — two versions in force, a
  superseded document pointing at another act, a revoking act outside the
  corpus, a marked PDF as a source.
- **Locators** on all 21 documents: incisos running I, II, III under one parent,
  alíneas a…z then aa…, each level resetting the ones below.
- **Retrieval**, measured separately from generation over 29 frozen cases, with
  the numbers held as a gate.
- **The contract's failure paths**, exercised rather than documented: a draft
  that cites a passage not retrieved for its request, a locator that is not a
  device inside its chunk, superseded text without the current version, revoked
  text without its revocation, output that is not JSON, JSON that is not a
  draft, a budget that stops before the call. Every path writes exactly one
  audit record.
- **The service**: not ready before the corpus and the index are loaded, and a
  recorded question answered end to end through the whole lock.

### Two evaluation flows, and the difference between them

Saying what separates them is worth more than either.

**The gate** runs on every push and pull request, against recorded responses:
deterministic, no network to any model, no API key, no card. That is what holds
the badge. CI that depends on a live model and a credit card does not run, and a
badge that depends on someone else's uptime lies.

**The drift monitor** is `workflow_dispatch` only. It asks the same frozen
questions of the live model and reports how far the answers moved from the
recordings — outcome, the passages they rest on, what the contract did — and how
many days old the recordings are, which is the number that says whether the
comparison still means anything. It **never gates**: a provider can update a
model without notice, and that is information to observe, not a reason to fail a
build. It costs about five cents a run:

```bash
ECLUSA_LIVE=1 OPENAI_API_KEY=... .venv/bin/python -m eclusa.eval drift
```

It writes to its own cassette and its own trail, never to the recordings the
gate replays.

## Where this grows

- **A durable sink for the trail.** In the cluster it is an `emptyDir` and
  belongs to the pod's lifetime.
- **More of the corpus.** The boundary is PLD/FT for BCB-supervised
  institutions, and every act deliberately left outside is an evaluation case:
  the penalty for the crime (federal law), gold-purchase procedures, COAF
  sectors, the FX family.
- **A `README.pt-BR.md`**, as the four sibling repositories have.

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

<p align="center">
  Built by <b>Karla Oliveira</b> · <a href="https://github.com/kabianca">@kabianca</a>
<!-- · <a href="https://www.linkedin.com/in/karlaboliveira/">LinkedIn</a> -->
  <br>
  <sub>Licensed under GPL-3.0 · Questions and critique are welcome | open an issue.</sub>
</p>
