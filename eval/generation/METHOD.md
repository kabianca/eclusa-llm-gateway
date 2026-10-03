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

## Open before the recording

`partial-344` expects the answer to cite `circular-3978-2020@v5 art. 23-A,
caput`, whose marker reads "(Incluído pela Resolução BCB nº 344, de
4/10/2023.)". Checked against the real index on 2026-10-03: **retrieval does
not deliver it.** For *"O que a Resolução BCB 344 mudou na Circular 3.978?"*
the top-8 is the boilerplate caput of every amending act — Resolução 344's own
art. 1º reads only "A Circular nº 3.978, de 23 de janeiro de 2020, passa a
vigorar com as seguintes alterações:", and the quoted block that names art.
23-A is deliberately not indexed. The link between act and provision lives in
the marker on art. 23-A, which similarity does not reach from this phrasing.

The expectation was written without verifying that, so it would fail on form
for a reason that is not the model's. Two ways out, the author's call:

- **Correct the expectation** to what the corpus can support today: cite
  `resolucao-bcb-344-2023@v1 art. 1º, caput` and declare the larger gap — the
  corpus shows *that* Resolução 344 amended the Circular, not *which*
  provisions. Honest about the pipeline as it stands; a weaker case than
  intended.
- **Make it a retrieval question first.** A marker index would fix it
  deterministically, the way the revocation notice is attached by rule: when a
  question names an act, also surface the provisions whose text carries that
  act's marker. That is a change to retrieval, so it goes in the frozen-first
  order — case and metric into `eval/retrieval`, baseline, then the mechanism —
  and if it works the README's boundary ("the corpus contains the act, not its
  diff") moves and must be rewritten.

Until this is decided, `partial-344` stays as written and is known to fail on
form; nothing is recorded, so nothing is green that should not be.
