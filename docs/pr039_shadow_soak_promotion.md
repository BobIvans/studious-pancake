# PR-039 — Shadow soak, replay and promotion evidence

This PR adds an offline evidence boundary for deciding whether the current
shadow/paper vertical has enough reproducible proof for a later human-reviewed
promotion discussion. It does **not** enable live mode, does not call RPC, does
not sign, and does not submit transactions.

## Boundary

`src.evidence.shadow_soak` consumes persisted shadow outcomes from one of two
sources:

1. the PR-013 `shadow_outcomes` SQLite table; or
2. an offline JSONL corpus with equivalent fields.

It produces a deterministic `pr039.shadow-soak-evidence.v1` JSON bundle with:

- sample count and soak duration;
- terminal reason counts;
- replay digest over stable decision identity;
- repayment/serialization mismatch count;
- unclassified failure count;
- false-positive rate where a positive conservative quote did not become a
  proven shadow success;
- predicted-vs-simulated PnL aggregates;
- blocking promotion reasons;
- an evidence hash;
- `human_review_required=true` and `live_enabled=false`.

## Default gates

The default thresholds intentionally fail closed:

- at least one sample;
- at least 72 hours between first created outcome and last completed outcome;
- zero repayment/serialization mismatches;
- zero unclassified failures;
- zero false-positive rate.

Operators can tighten thresholds for a specific review using the CLI options,
but this PR does not define an automatic promotion path. A passing bundle is
only evidence for human review, not permission to trade live.

## CLI

```bash
python scripts/shadow_soak_report.py --sqlite path/to/shadow.sqlite --output evidence.json
python scripts/shadow_soak_report.py --jsonl path/to/corpus.jsonl --min-samples 100
```

The command exits with `0` only when all configured evidence gates pass. It exits
with `2` when the bundle is well formed but blocked by PR-039 promotion gates.
Malformed input raises an error and exits non-zero.

## Replay determinism

Replay determinism is represented by a digest over each outcome's stable
identity:

- attempt id;
- plan hash;
- message hash;
- reconciliation hash;
- terminal reason;
- simulated executable PnL;
- repayment proof state.

Changing a replay decision, message identity, reconciliation hash or terminal
classification changes the replay digest and therefore the evidence hash.

## Non-goals

- No live canary enablement.
- No sender/Jito/RPC integration.
- No attempt to hide or auto-accept repayment/serialization mismatches.
- No durable journal migration beyond reading the existing `shadow_outcomes`
  table.
- No automatic merge/promotion decision; the bundle always requires human
  review.
