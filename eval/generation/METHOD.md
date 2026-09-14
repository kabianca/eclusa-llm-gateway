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

- `answerable` — the corpus answers; expected `answered`, with the units a
  correct answer must cite.
- `version` — the answer depends on the version; the consolidated unit must be
  cited, and if the original is cited the consolidated must be too (the
  contract enforces it; the expectation records it).
- `partial` — the corpus covers part; expected `partial` with a declared gap.
- `refusal` — a near-miss: adjacent to the corpus, not in it; expected
  `refused`.
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
