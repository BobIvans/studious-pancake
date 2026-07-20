# PR-060 — real shadow soak and promotion evidence

PR-060 adds a fail-closed evidence contract for the first real shadow-soak
promotion milestone.  It intentionally does **not** run trading logic, sign,
submit, or enable live mode.

## Why this exists

The roadmap requires a real shadow soak before limited-live canary promotion.
That evidence is not the same thing as green unit tests or a synthetic fixture.
A valid package must show that the supported paper/shadow vertical ran long
enough, produced replayable data, wrote paper outcomes, reconciled those
outcomes, and was reviewed by a human before being fed into the release gate.

## New boundary

`src.shadow_soak` exposes:

- `ShadowSoakEvidence` — immutable evidence envelope for one run.
- `ShadowSoakMetrics` — candidate, simulation, reconciliation, quota, latency,
  and P&L counters.
- `ReplayEvidence` — deterministic replay counts and corpus digest.
- `SoakArtifactReference` — digest-pinned raw events, replay corpus, metrics,
  and operator review artifacts.
- `ShadowSoakThresholds` — default PR-060 policy with a 72-hour minimum.
- `evaluate_shadow_soak(...)` — fail-closed promotion evaluator.
- `to_pr047_shadow_soak_reference(...)` — adapter into the existing PR-047
  `EvidenceKind.PR039_SHADOW_SOAK` release-gate slot.

## Default acceptance policy

The default evaluator blocks promotion unless all of the following hold:

1. the run lasted at least 72 hours;
2. all required vertical stages were observed:
   discovery, capital, planner, compiler, simulation, reconciliation,
   lifecycle;
3. at least one candidate and one reconciled outcome were observed;
4. deterministic replay has a non-empty corpus and 100% pass rate;
5. reconciliation, message hash, repayment, and ambiguity mismatches are zero;
6. quota exhaustion, RPC errors, and accepted stale data are zero;
7. raw-events, replay-corpus, metrics-report, and operator-review artifacts are
   pinned by non-placeholder SHA-256 hashes;
8. the run is human reviewed;
9. the evidence bundle is signed or at least points to a signed evidence
   artifact reference.

Provider 5xx errors, stale-data rejections, and negative shadow P&L are warnings
rather than automatic blockers because the correct response may be to reject or
skip trades while keeping the soak valid.  Unexplained accepted stale data is a
blocker.

## Non-goals

This PR does not:

- claim that a real 72-hour soak has already happened;
- alter `flashloan-bot paper-shadow` runtime composition;
- add or modify senders;
- enable canary or live trading;
- bypass PR-047 release-gate signoff requirements;
- replace PR-059 durable paper/shadow runner work.

## Expected future run artifact flow

After PR-059 wires the real durable runner, an operator should produce:

```text
artifacts/pr060/raw-events.jsonl
artifacts/pr060/replay-corpus.jsonl
artifacts/pr060/metrics.json
artifacts/pr060/operator-review.md
artifacts/pr060/shadow-soak-evidence.json
artifacts/pr060/shadow-soak-evidence.sig
```

The evidence JSON can then be loaded by a future CLI wrapper, evaluated with
`evaluate_shadow_soak(...)`, and converted into a PR-047 evidence reference via
`to_pr047_shadow_soak_reference(...)`.

## Review guidance

For this PR, reviewers should check the schema and tests rather than expecting
real mainnet evidence.  The correct status after merge is: the repository has a
PR-060 evidence gate, but it is **not** shadow-soak complete until a real run
package passes the gate and is attached to a release manifest.
