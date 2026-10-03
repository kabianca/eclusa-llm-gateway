# Generation evaluation — who grades, and what is frozen

Written 2026-09-14, before any live call. The decision that shapes the files
here is *who says an answer is right*:

- An LLM judge would add a second non-deterministic component to a project
  whose thesis is determinism. Discarded.
- A rule-based grader reaches form (outcome, citations) but not content.
- The author grades by hand, once. The cases are few, the domain is one she
  can judge, and the grades are committed as the expected result. From then on
  the evaluation is deterministic: recorded response + committed grade =
  regression test, with no judge and no network.

So a case holds three layers, each written at a different moment:

1. **Expectation** (`cases.json`, before recording) — the outcome and the
   provisions a correct answer must cite, in prose why. Drafted from the corpus
   text; confirmed by the author before the live run.
2. **Recording** (`recordings.jsonl`, `responses/<id>.json`, the audit trail of
   the run) — what the model produced, once, live, through the whole lock:
   retrieval, budget, contract, audit. Written by `python -m eclusa.eval record`.
3. **Grade** (`grades.json`, after reading the responses) — the author's verdict
   on content, `pass` or `fail`, with a note. Nothing is graded by the code.

The gate (`python -m eclusa.eval generation`, and the test that wraps it once
recordings exist) replays every case through the gateway in recorded mode and
requires: the replay reproduces the recorded response, the response matches
the expectation in outcome and citations, and the grade says `pass`. A `fail`
grade is not hidden: it is reported as a known failure with its note, and it
is what the README's reversal condition on the model is measured against —
*if the mini violates the contract on most cases, that is a finding to record
before any model change*.

## Kinds

Every citation in an expectation names the **document**, version included
(`circular-3978-2020@v5`), never the act alone. Where a provision is identical
in both versions the act-level scope would also be satisfiable, but writing it
out keeps the expectation explicit about which text a correct answer stands on,
and matches what the version-aware retrieval actually delivers.

- `answerable` — the corpus answers; expected `answered`, with the units a
  correct answer must cite.
- `version` — the answer depends on the version; the consolidated unit must be
  cited, and if the original is cited the consolidated must be too (the
  contract enforces it; the expectation records it).
- `partial` — the corpus covers part; expected `partial` with a declared gap.
  Two shapes of partial are tested: the corpus holds a *neighbouring* subject
  (gold red flags, not purchase procedures), and the corpus holds the right
  provision for the *wrong addressee* (the Coaf deadline, which binds
  BCB-supervised institutions, asked about a jeweller). The second is the
  sharper one: the dangerous error is not inventing a number, it is
  transplanting a true one.
- `refusal` — a near-miss where the corpus holds **nothing** on the subject;
  expected `refused`. The line against `partial`: if the corpus does say
  something that bears on the question, refusing throws it away and the case
  belongs to `partial` instead.
- `ambiguous` — expected `refused` with the ambiguity named.
- `revoked` — the question names a revoked act; expected an answer that cites
  the revocation notice (or a partial that does), never a silent answer from
  the revoked text.

## What the first live call found (2026-10-03)

One case, `answer-10`, US$ 0.00215 — and a `contract_violation`. The model got
the document right, the chunk right and the answer right, and wrote the locator
as `art. 10, caput (Circular nº 3.978, de 23 de janeiro de 2020)`. The header
of every passage used to render `locator={locator} ({act title})`, with the
title glued to the locator and no separator, while the prompt says to copy the
locator exactly. The model obeyed; the header lied.

Fixed where the fault was. The title moved to its own line and the three fields
to copy sit on the next, with `locator` last so it ends at the newline. The
contract was not touched: accepting a locator with a suffix would have given
away the guarantee that a citation names a device that exists in the chunk —
the one thing this project claims.

Two things this confirms. Spending one call before fourteen was worth it: the
cassette is append-only and this would have been fifteen useless entries.
And the blocked draft in the audit record is what made the diagnosis possible
in one reading — "the model tried to say X and was stopped", with X in full.

The trial's artifacts were deleted rather than kept: the prompt is part of the
recording key, so that entry was already unreachable, and a dead entry in an
append-only file is worse than no entry.

## What the first full run found (2026-10-03)

Fifteen cases, US$ 0.0457, four contract violations — and three of the four were
faults of mine, which is the point of looking at the blocked drafts rather than
at the counts.

**Two rules were written per sentence and had to be per answer.** For *"o que o
texto original previa?"* the model answered in three statements: the original
provided 1º de julho (citing v1), the text in force provides 1º de outubro
(citing v5), the change came from Circular 4.005 (citing it). That is a better
answer than one sentence carrying every citation, and `superseded_without_current`
refused it, because it demanded the counterpart inside the same statement. Same
for `revoked_without_notice` on *"o que a 3.461 dizia sobre PEP?"*: five
statements of what the act required and a sixth stating it was revoked, citing
the notice — refused five times. The obligation belongs to the answer: the answer
may not rest on superseded or revoked text alone, and which sentence carries the
counterpart is the model's business. The superseded rule is now matched per
locator as well, so the old art. 70 is answered by the current art. 70 and not
by any other provision of the act.

Changing a rule after seeing results is adjacent to tuning the test to the
system, so what did *not* change is worth stating: the purpose of both rules is
word for word what it was. The bug was in the unit the obligation was expressed
over.

**A refusal carrying statements was reported as unparseable.** The model refused
*"qual é a pena para o crime de lavagem?"* and attached one cited statement about
what the Circular is for, plus a gap. The JSON was perfect; the shape rule
rejected it, and the trail said "the output is not a draft", which sends the
diagnosis the wrong way. Now the trail distinguishes output that is not JSON
from JSON that is not a draft, and the prompt says what it never said: a refusal
goes with `statements` and `gaps` empty, and context goes in `refusal_note` — if
there is a cited statement *and* a gap, the outcome is `partial`.

**A refusal by the lock was passing as a refusal by the model.** `refusal-pena`
matched its expectation on form, because the expectation asks for `refused` and
the caller did receive a refusal — one produced by the contract catching a bad
answer, not by the model declining. Those are opposites: one is the system
working, the other is the system being saved from itself. `compare` now says so.

**One violation was the system working.** For *"quais informações cadastrais a
Circular 3.461 exige?"* — present tense, revoked act — the model answered "a
Circular 3.461 **exige**…" without stating the revocation, which was retrieved
and sitting in the context. The contract stopped it. That is the case this
project exists to catch, and it is the only one of the four that the model got
wrong.

The run was therefore re-recorded after the fixes: the prompt is part of the
recording key, so measuring with one prompt and running with another would have
left the recordings describing a system that no longer exists.

## Precautions for the live run

- The run is the only live call in the project. It needs `ECLUSA_LIVE=1` and
  the key in the environment; without both the recorder refuses.
- Per request, the budget's hard stop; per run, `--max-total-usd` in the
  recorder, summed over worst cases before each call. And **a spending cap on
  the provider account**, set in the provider's dashboard — the code protects
  each request, a cap on the account catches the loop the code did not foresee.
- Recordings are appended, never rewritten. Re-recording is a deliberate act
  with a new cassette and a note here. Because of that, spend **one** call
  first — `make record ARGS="--only answer-10"` — and look at it before
  committing the rest: a first run that fails on the API shape would otherwise
  leave fifteen useless entries inside an append-only file.

## CHANGELOG

- 2026-09-14 — cases and expectations drafted; awaiting the author's
  confirmation and the live run.
- 2026-10-03, amendment 1 — the author reviewed every expectation against the
  corpus text and changed four things, before any recording existed:
  1. The jeweller question moved from `refusal` to `partial`
     (`refusal-joalheria` → `partial-joalheria`). The corpus does set a
     reporting deadline (art. 48, § 2º), for BCB-supervised institutions;
     refusing outright discards it, and answering with the number alone
     transplants it to a sector this corpus does not regulate. Partial is the
     outcome that says both. The refusal set keeps two clean near-misses
     (`refusal-pena`, `refusal-multa`), where the corpus holds nothing at all.
  2. `partial-344` keeps its outcome, with the reason corrected: Resolução 344's
     only effect *was* art. 23-A and the consolidated marker says so, so the
     earlier "the corpus does not hold the effect" was wrong. What the corpus
     cannot hold is the proof that nothing else changed — the gap is epistemic,
     and that is what the answer must declare.
  3. `revoked-present-tense` now requires art. 2º, caput alongside the
     revocation notice. Requiring only the notice would have passed an answer
     that stated the revocation and answered nothing.
  4. Every citation scope is version-pinned (see above).
- 2026-10-03, amendment 2 — `partial-344` became `answer-344`: the corpus does
  say what Resolução 344 changed, and after the retrieval amendment the index
  does too. The section below has the chain.

## Amendment 2 — the question that was open is answered (2026-10-03)

`partial-344` expected the answer to cite art. 23-A of the consolidated text,
and checking the expectations against the live index showed retrieval did not
deliver it: the link between an act and the provisions it changed lives in a
marker that similarity does not reach from "o que a Resolução 344 mudou?".

The author's reading closed it. The corpus **does** hold what Resolução 344
changed, verbatim — its art. 1º is followed by the full text it gives to art.
23-A, closing with "(NR)". What did not hold it was the index, because the
chunker dropped every block an amending act transcribes: ten per cent of the
corpus, 183 of 1,873 paragraphs. That was a decision of mine dressed as a
property of the corpus.

So the transcriptions are indexed, as a third kind of chunk joined to the
article that transcribes them, ranked below text in force unless the question
names the amending act — the rule already used for revoked acts. Frozen first
in `eval/retrieval` (amendment 2 there), then built, then measured:
`amendment_text_reachable` 0.0 → 1.0, no regression anywhere, and
`mrr_in_force` 0.8042 → 0.8458.

The case becomes `answer-344`, kind `answerable`, expecting `answered` and a
citation of `resolucao-bcb-344-2023@v1 art. 1º, caput`. The system prompt
gained the matching rule: a transcribed passage may be cited for what an act
changed, never as the wording in force.

Nothing is open before the recording now.
