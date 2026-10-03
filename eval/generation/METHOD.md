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

## Precautions for the live run

- The run is the only live call in the project. It needs `ECLUSA_LIVE=1` and
  the key in the environment; without both the recorder refuses.
- Per request, the budget's hard stop; per run, `--max-total-usd` in the
  recorder, summed over worst cases before each call. And **a spending cap on
  the provider account**, set in the provider's dashboard — the code protects
  each request, a cap on the account catches the loop the code did not foresee.
- Recordings are appended, never rewritten. Re-recording is a deliberate act
  with a new cassette and a note here.

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
