# Retrieval evaluation — frozen before the retrieval layer was touched

Frozen on 2026-09-14, on branch `feat/frozen-corpus-and-gateway`, *before* any
version-aware retrieval existed. The cases in `cases.json` and the metrics below
were written first, the baseline was measured second, and only then was the
retrieval layer changed. The "after" number is worth exactly the order in which
it was produced: a set chosen while tuning would measure the tuning.

The evidence is the aggregate over the set. One question improving proves
nothing; the entry-into-force question (0.9145 vs 0.9028) illustrates the trap
in the README, it does not measure the fix.

## Setup

- Index: the committed corpus (`corpus/manifest.json`), chunk policy `units-v1`,
  `intfloat/multilingual-e5-small` at the pinned revision. Exact search.
- `k = 8`, the gateway's own `k`. Everything below is over the top-8 chunks.
- A hit for a case is a chunk whose document belongs to the expected act and
  whose unit citation is one of the accepted units (a unit is a caput or a §
  with what nests under it — the chunk's `citation`).

## Case kinds

- `changed` — the answer differs between the original (v1) and the consolidated
  (v5) text of Circular 3.978. The version trap proper.
- `unchanged` — the provision is identical in v1 and v5. Control: in-force must
  still be preferred, by policy, not by luck.
- `topic` — the question names no act; Circular 3.978 (in force) and Circular
  3.461 (revoked) both regulate the topic. The in-force act must rank first.
- `names_revoked` — the question names the revoked act; its text must be found
  *and* its revocation notice must be within reach, so the contract can require
  the revocation to be stated. Adversarial for the "revoked below in force"
  rule: here forcing the act in force first would be the wrong answer.
- `asks_original` (amendment 1) — the question is legitimately about the
  superseded wording. Adversarial for the "in force first" rule: the original
  must remain within reach, so the contract's "cite both" can be satisfied.

## Metrics (all fractions over the cases of the kinds they apply to)

- `hit@8` — the expected unit of the expected act is in the top-8. All kinds.
- `in_force_first` — among the top-8 chunks matching the expected unit, the
  best-ranked one belongs to the document in force (v5), not the superseded
  one (v1). No hit at all counts as a failure. Kinds `changed`, `unchanged`.
- `mrr_in_force` — 1 / rank of the first chunk matching the expected unit in
  the in-force document; 0 when absent from the top-8. Kinds `changed`,
  `unchanged`.
- `revoked_below_current` — the first chunk of the expected in-force act ranks
  above the first chunk of the competing revoked act; a revoked act absent from
  the top-8 counts as success, an in-force act absent counts as failure. Kind
  `topic`.
- `notice_with_revoked` — when any chunk of the revoked act is in the top-8,
  that act's revocation notice is in the top-8 too. Kind `names_revoked`.
- `named_first` (amendment 1) — the top-1 chunk belongs to the act the question
  names. Kind `names_revoked`. Guards the *exception* of the revoked-below rule:
  a rule that always fired would fail this.
- `superseded_reachable` (amendment 1) — the expected unit from the *superseded*
  document is in the top-8. Kind `asks_original`. Guards the exception of the
  in-force-first rule: a layer that dropped history would fail this. `hit@8`
  for this kind counts the superseded document's unit.

Three of the metrics — `in_force_first`, `revoked_below_current`,
`notice_with_revoked` — went to 1.0 because the layer guarantees those
properties by construction. They measure that the rule was applied, not that
the rule is right: they are **regression guards** that keep a property from
being lost. The number that measures retrieval itself is `hit@8`, which the
layer does not move.

## Rules

- Cases and metrics do not change after the baseline. A demonstrably wrong
  expected unit may be corrected, and the correction, its reason and the date go
  in `CHANGELOG` at the end of this file — and the baseline is re-measured and
  both numbers reported.
- Every expected unit was checked by opening the corpus text, not by running
  the retriever and copying what it returned.

## Results

- `results-before.json` — the index alone (`python -m eclusa.eval retrieval
  --retrieval raw`), measured 2026-09-14 before the retrieval layer existed.
- `results-after.json` — the version-aware layer (`--retrieval version`, the
  default and what the gateway uses), measured 2026-09-14 after it was written.
  No score was changed between the two; the layer reorders and attaches.
- `tests/test_eval_retrieval.py` holds the gate: the after numbers may not
  regress.

| metric | before | after |
|---|---|---|
| hit@8 (24 original cases) | 0.9167 | 0.9167 |
| in_force_first | 0.25 | 1.0 |
| mrr_in_force | 0.3844 | 0.8042 |
| revoked_below_current | 0.6 | 1.0 |
| notice_with_revoked | 0.0 | 1.0 |
| hit@8 (26 cases, amended set) | 0.9231 | 0.9231 |
| named_first (amendment 1) | 1.0 | 1.0 |
| superseded_reachable (amendment 1) | 1.0 | 1.0 |

The two amendment metrics read 1.0 before *and* after: the rules do not fire
where they must not, and the layer did not lose the history it was told to
keep. They exist so that a future change cannot make either rule always fire.

## CHANGELOG

- 2026-09-14 — frozen.
- 2026-09-14, amendment 1 — the set tested the two rules only where they must
  fire. It had questions naming the revoked act, but no metric caught a rule
  that always fired; it had no question legitimately about the superseded
  wording. Added metric `named_first` (kind `names_revoked`), kind
  `asks_original` with two cases and metric `superseded_reachable`. The 24
  original cases and their metrics are untouched; `results-before.json` and
  `results-after.json` were re-measured on the amended set of 26 (the values
  for the original cases are unchanged by construction, and reported below).
