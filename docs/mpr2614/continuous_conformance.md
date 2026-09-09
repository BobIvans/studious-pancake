# MPR-2614 — Continuous Production Conformance Sentinel

## Purpose

MPR-2614 is a post-release conformance consumer. It answers whether the currently observed runtime still matches the exact released/operating generation. Its positive output is only a bounded monotonic `RuntimeConformanceLease`; it is never live permission.

## Actual predecessor observation

Observed while implementing this branch on 2026-09-09:

- accepted `main`: `d23f82e20d10345926742352739b1a6ca3f7a859` (MPR-2611 / PR #482 merged);
- MPR-2612 branch: `codex/mpr-2612-final-release-gate` @ `bd6fc670a23233c633f38310f875bdac3db6cb4c`;
- MPR-2613 branch: `codex/mpr-2613-guarded-production-operations` @ `a03abe4f93a37b1b6cac8fe5a06c747f9564da7d`;
- MPR-2614 is stacked on the observed MPR-2613 head so it can consume `AcceptedReleaseIdentity` and `OperatingEnvelope` instead of inventing a second release/operations contract.

The MPR-2612 and MPR-2613 branches were both based independently on the same accepted main and were diverged when observed. MPR-2614 therefore does not guess a merge result between them. MPR-2613 already models MPR-2612 output through `AcceptedReleaseIdentity`; this PR consumes that adapter and requires `receipt_verified=true` before a positive lease can exist.

## Ownership boundary

MPR-2614 owns:

- exact post-release runtime identity comparison;
- independent trusted-time freshness checks for PR-201 readiness snapshots;
- monotonic bounded conformance leases;
- release/process/boot generation fencing of leases;
- fail-closed drift classification;
- a `suspension_required` result for the existing latch/guarded-operations consumer;
- no-auto-rearm semantics after sticky suspension.

MPR-2614 does **not** own:

- final release/promotion (MPR-2612);
- operating envelope, capital/resource caps or operating state (MPR-2613);
- human approval/recovery (MPR-2603);
- signer/submission (MPR-2608);
- canary authority (MPR-2609);
- finalized realized PnL (MPR-2610);
- qualification/evidence authenticity (MPR-2611);
- provider governance or protocol qualification.

## Reproduced false positives closed at the post-release trust boundary

### P2614-01 — stale PR-201 readiness

`ManagementReadinessSnapshot.evaluate()` does not use trusted current time. A snapshot with `observed_at_ms=0` can still report `healthy=true` when producer booleans are green.

MPR-2614 treats PR-201 as an observation producer and independently compares `observed_at_ms` with `trusted_now_ms` under `ConformancePolicy.max_snapshot_age_ms` and `max_future_skew_ms`. Stale or future-dated readiness cannot produce a lease.

### P2614-02 — wrong release generation can look operator-ready

The historical PR-201 `operator_readiness_report()` combines blockers but does not cross-bind source/image/config/contract identities to its `ReleaseImageManifest`. MPR-2614 independently binds:

- source commit;
- runtime image digest;
- deployment image digest;
- config hash;
- contract evidence hash;
- accepted MPR-2613 release identity;
- cluster genesis;
- provider, signer and submission generations;
- provider/deployment digest.

Any mismatch yields a stable `MPR2614_*_DRIFT` reason and no lease.

## Lease semantics

A lease is bound to:

- release generation and accepted release-decision hash;
- release-pin semantic digest;
- operating-envelope hash;
- process ID and boot generation;
- exact observation semantic digest;
- monotonic issue/expiry times.

Wall-clock rollback cannot extend a lease because lease validity accepts only monotonic time. Restart cannot reuse a lease because boot generation is part of validity. A new release generation invalidates old leases.

`sticky_suspension_active=true` blocks lease refresh even when the latest heartbeat is otherwise healthy. A later green observation therefore cannot auto-clear an incident; recovery remains an upstream human/governed operation.

## Safety invariants

Every `ConformanceDecision` hard-codes:

- `live_enabled=false`;
- `signer_allowed=false`;
- `submission_allowed=false`;
- `automatic_rearm_allowed=false`.

The sentinel does not import signing or sender modules and performs no network I/O.

## Focused coverage

`tests/test_mpr2614_continuous_conformance.py` covers the two reproduced false positives and key adversarial cases from T2614-001..040: stale/future observations, source/image/config/contract drift, deployment image drift, lease expiry, monotonic lifetime, restart fencing, provider/genesis/signer drift, unresolved economic ambiguity, SLO/data-loss suspension, sticky no-auto-rearm, tamper lineage, release-generation invalidation, and sender/signing/live denial.

## Remaining integration before a production deployment can consume this sentinel

1. Accept/merge MPR-2612 and reconcile its final receipt/output contract with MPR-2613's `AcceptedReleaseIdentity`.
2. Accept/merge MPR-2613 and rebase this stacked PR on its accepted head.
3. Wire `suspension_required` into the existing canonical hard-latch mutation with caller-owned durable transaction semantics; do not add a second latch store here.
4. Materialize real heartbeat/provider/deployment/economic evidence and run elapsed fault/partition/restart campaigns.
5. Add installed operator status projection after the existing CLI owner is known on the accepted predecessor heads.

These are integration/deployment prerequisites, not reasons to fabricate a release receipt or a second authority inside MPR-2614.
