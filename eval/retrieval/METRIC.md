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
- `asks_diff` (amendment 2) — the question names an amending act and asks what
  it changed. The answer is the text the act quotes, which was not indexed at
  all before this amendment.

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
- `amendment_text_reachable` (amendment 2) — the expected unit of the named
  amending act is in the top-8 **as an amendment chunk**, i.e. carrying the
  text the act quotes rather than only its "passa a vigorar com as seguintes
  alterações:" caput. Kind `asks_diff`.

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

Three measurements, all on the 29-case amended set so the denominators match:

- `results-before.json` — the index alone (`--retrieval raw`), the state before
  any retrieval layer existed.
- `results-after.json` — the version-aware layer (`--retrieval version`), the
  state before amendment 2. No score changed between the two: the layer
  reorders and attaches.
- `results-amendment.json` — the same layer over an index that also holds the
  text amending acts transcribe (amendment 2). The chunking changed, so the
  index was rebuilt and `chunk_policy` went to `units-v2`.

`tests/test_eval_retrieval.py` holds the gate: these numbers may not regress.

| metric | raw index | version layer | + transcribed text |
|---|---|---|---|
| hit@8 | 0.931 | 0.931 | 0.931 |
| in_force_first | 0.25 | 1.0 | 1.0 |
| mrr_in_force | 0.3844 | 0.8042 | **0.8458** |
| revoked_below_current | 0.6 | 1.0 | 1.0 |
| notice_with_revoked | 0.0 | 1.0 | 1.0 |
| named_first (amendment 1) | 1.0 | 1.0 | 1.0 |
| superseded_reachable (amendment 1) | 1.0 | 1.0 | 1.0 |
| amendment_text_reachable (amendment 2) | 0.0 | 0.0 | **1.0** |

Three of these — `in_force_first`, `revoked_below_current`,
`notice_with_revoked` — are 1.0 because the layer guarantees the property by
construction; they measure that the rule was applied, not that the rule is
right, and they are regression guards. `named_first` and
`superseded_reachable` read 1.0 throughout: the rules do not fire where they
must not. `hit@8` is the number that measures retrieval, and no change has
moved it: the layer cannot find what the embeddings miss.

`mrr_in_force` rising with amendment 2 has one cause, checked case by case:
`changed-68-cambio` went from 0.33 to 1.0. It asks whether Circular 3.978
amends Circular 3.691 on the FX market. Art. 68 of the original 3.978 is the
article that does it, and its chunk used to be the bare caput — "passa a
vigorar com as seguintes alterações:" — because the transcription that
actually mentions câmbio was dropped. With the transcription in the chunk, the
article the question is about finally outranks its neighbours.

## CHANGELOG

- 2026-09-14 — frozen.
- 2026-10-03, amendment 2 — ten per cent of the corpus (183 of 1,873
  paragraphs) was the text that amending acts quote, and none of it was
  indexed: the chunker dropped quoted segments so that they would not compete
  with the consolidated text that already carries their provenance markers. The
  side effect, found while checking the generation expectations against the
  live index, is that "what did act X change?" had no answer in the index even
  though the corpus holds the answer verbatim — Resolução 344's art. 1º is
  followed by the full text it gave to art. 23-A. Added kind `asks_diff` with
  three cases and metric `amendment_text_reachable`, frozen here before the
  chunker and the ranking changed. **The adversarial guard for the new rule is
  already in the set**: `changed-23a-renegociacao` asks the substance without
  naming Resolução 344, so `in_force_first` fails if an amendment chunk ever
  outranks the law in force. The 26 earlier cases and their metrics are
  untouched.
- 2026-09-14, amendment 1 — the set tested the two rules only where they must
  fire. It had questions naming the revoked act, but no metric caught a rule
  that always fired; it had no question legitimately about the superseded
  wording. Added metric `named_first` (kind `names_revoked`), kind
  `asks_original` with two cases and metric `superseded_reachable`. The 24
  original cases and their metrics are untouched; `results-before.json` and
  `results-after.json` were re-measured on the amended set of 26 (the values
  for the original cases are unchanged by construction, and reported below).
