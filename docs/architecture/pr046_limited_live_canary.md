# PR-046 — Limited-live canary and automatic safety latches

## Purpose

PR-046 defines the smallest reviewable live admission boundary. It is not a
replacement for PR-045 transport and it is not an unrestricted `LIVE=true`
switch.

The new `src.live_canary` package contains no signer, RPC sender, Jito client or
network transport. It returns a typed admission decision and reserves at most
one outstanding message identity. A later sender integration must consume that
identity without recompiling, mutating or bypassing the decision.

## Default-deny contract

`CanaryPolicy()` is disabled and shadow-only. It has empty allowlists and zero
exposure limits, so default construction cannot authorize a transaction.

An enabled deployment policy must explicitly define:

- `mode=limited_live`;
- one or more allowed pairs, programs and execution providers;
- a principal cap bounded by an immutable deployment ceiling;
- a wallet-spend cap bounded by an immutable deployment ceiling;
- a minimum wallet reserve;
- daily-loss, consecutive-failure, freshness and RPC-divergence limits;
- exactly one outstanding submission;
- a short operator confirmation TTL.

The existing PR-018 `src.execution.live_control` module and its sample YAML are
not the PR-046 authority. The supported runtime/live sender remains disabled
until the PR-045 integration explicitly consumes this new boundary.

## Multi-step operator enablement

Limited live requires three distinct human-controlled steps:

1. Attach a passing PR-039 `PromotionEvidenceBundle` and record a human review
   reference. The bundle must retain `human_review_required=true` and
   `live_enabled=false`.
2. A human operator acknowledges the exact policy hash and exact PR-039 evidence
   hash using the fixed acknowledgement text.
3. The same human operator arms the canary before the acknowledgement expires.

AI and automation identities cannot review evidence, acknowledge policy, arm,
clear latches, engage the manual kill switch or roll back modes. AI may assist
analysis outside this boundary but `ai_authority` is always false in the report.

## Admission checks

Every candidate is checked against:

- active mode, fresh arming receipt and reviewed PR-039 evidence;
- sticky safety latches;
- zero existing outstanding submissions;
- allowlisted pair, provider and complete program set;
- configured principal and wallet-spend caps;
- post-spend wallet reserve;
- candidate/data freshness;
- RPC slot divergence;
- daily-loss, consecutive-failure and reconciliation state.

An allowed decision is bound to `attempt_id`, candidate hash, plan hash, message
hash, policy hash, evidence hash and evaluation time. Reservation fails if any
identity changes.

## Automatic latches

The following latches are sticky and disarm the canary:

- low wallet balance;
- daily loss limit;
- consecutive failure limit;
- stale or future-dated data;
- reconciliation ambiguity;
- RPC slot divergence;
- manual kill switch.

Latches can be cleared only by a human while the controller is in shadow mode
and no submission is outstanding. Clearing a latch does not re-arm live.

## Mandatory reconciliation

After an allowed decision is reserved, every new admission is blocked until a
matching post-trade reconciliation is recorded.

- `success` clears the outstanding identity and resets consecutive failures;
- `failure` clears the identity, records realized PnL and increments failures;
- `indeterminate` keeps the outstanding identity and activates the reconciliation
  ambiguity latch.

A reconciliation whose attempt or message hash differs from the outstanding
identity is itself indeterminate and fails closed.

## Rollback

A human operator can roll the controller back to shadow without changing code,
configuration schema or deployment artifacts. Rollback removes arming and
acknowledgement state. Re-entry requires a new acknowledgement and arm step.

## Parallel roadmap work

The branch starts directly from the current `main`. PR-039 evidence and PR-041
durable lifecycle support are already present. PR-042–PR-045 are being developed
in parallel and are not copied into this patch.

After those PRs merge, PR-046 must be replayed onto the newest `main`. The final
integration review must verify that:

- PR-042 readiness exposes every active latch and outstanding identity;
- PR-043 signer/security policy cannot be bypassed;
- PR-044 failure injection activates these latches under degradation;
- PR-045 sender accepts only the exact reserved decision/message identity.

## Verification

```bash
python -m black --check src/live_canary tests/test_pr046_canary_*.py
python -m mypy --config-file mypy.ini src/live_canary
python -m pytest tests/test_pr046_canary_enablement.py tests/test_pr046_canary_latches.py -q
python -m compileall -q src/live_canary tests/test_pr046_canary_*.py
python scripts/verify_repo.py
```
