# AGG-08 — isolated signing, submission and finalized settlement closure

Base inspected: `main@0c4f216a62d62b20f6fb4ec4bbd0548cea58df65`.

## Scope and ownership

AGG-08 is an integration closure over existing authorities. It does not create a
second signer, sender, capital authority, lifecycle database, or economic ledger.

Reused canonical owners:

- lifecycle: `src.durability.unified_authority_pr02:UnifiedLifecycleAuthority`;
- capital: `src.economics.durable_reservations:DurableCapitalCoordinator`;
- isolated signer: MPR-2608 plus PR-202 signer-boundary evidence;
- reviewed permit: `src.live_boundary.pr202_isolated_signer_settlement`;
- canonical RPC/Jito sender: `src.submission.permit_bound` and
  `src.submission.canonical_sender`;
- crash/reconcile boundary: `src.submission.durable` and
  `src.submission.lifecycle_integration`;
- limited-live latches: `src.live_canary`;
- finalized economics: `src.execution.core_v1_finalized_settlement` and MPR-2610.

The new `src.live_boundary.agg08_execution_closure` module binds those owners at
the final effect-adjacent boundary and remains compile-time default-off.

## LIVE-01 — exact execution binding

`ExecutionProfile` binds qualification, release/config/policy/risk generations,
cluster/wallet identity, assets, programs, lenders, routes, transport, principal,
native-debit, tip and failure budgets, and expiry. Slumlord remains a required
financing dependency for this AGG-08 profile.

`Agg08ExecutionGate.admit_pre_sign()` fail-closes on profile/auth/reviewer drift,
signer-boundary mismatch, expired or latched canary state, changed permit,
plan/message/blockhash drift, stale state, exact-simulation mismatch, scope drift,
unresolved outcomes, kill switch, insufficient reservation, or any declared cap
breach. The effect gate defaults to false.

## LIVE-02 — canonical sender reuse

`build_submission_permit_request()` performs no network I/O. It verifies the
accepted pre-sign decision, exact signed primary message, simulation identity,
reviewed-permit lifetime, transport and Jito tip semantics, then delegates to the
existing `permit_request_from_payload()` contract.

The existing sender/lifecycle owners retain durable pre-dispatch intent,
ACK-not-finality semantics, ambiguous-outcome recovery and no blind
RPC/Jito fallback.

## LIVE-03 — finalized-only landing labels

`finalized_landing_label()` accepts only terminal finalized Core-V1/MPR-2610
economic evidence. `UNKNOWN_QUARANTINED` and
`FINALIZED_PENDING_ECONOMICS` cannot become landing labels. Paper, simulation,
transport ACK and counterfactual records are not promoted to real landing labels.

## NF coverage

The module contains an explicit 21-row map for NF-194, NF-195, NF-196 and
NF-198…NF-215. Existing execution primitives are REUSED rather than reimplemented.
NF-215 remains `BLOCKED_PREREQUISITE`: every new lender × venue × strategy
combination requires a new qualification generation; one canary is not wildcard
authorization.

## Verification

Focused tests cover:

- compile-time/default-off behavior;
- an exact fully-bound offline fixture;
- message/simulation and blockhash mutation;
- stale profile generation;
- kill switch and unresolved outcome;
- principal/native-debit/failure budget caps;
- required Slumlord financing;
- expired canary arming;
- post-sign delegation to the existing submission-permit contract;
- finalized-only landing labels;
- complete 21-NF static coverage.

Repository CI remains authoritative. Relevant predecessor regression surfaces are
MPR-2608 isolated signer, PR-045 permit-bound submission, PR-080 lifecycle
integration, MPR-2610 finalized economics and CORE-V1 closure.

## Safety and operational status

This PR performs no real signature, RPC/Jito submission, wallet funding, remote
account mutation or trading operation. `AGG08_COMPILE_TIME_LIVE_ENABLED=False`.
Code merge is not live authorization and does not authorize spending.

Current `main` still has a MarginFi-specific Core-V1 finalized decoder and does
not contain the later AGG-03 Slumlord/Jupiter-Lend lender-neutral production
profile described by the new master plan. Therefore this PR can close the
reviewable AGG-08 integration boundary offline, while operational status remains
`UNQUALIFIED/BLOCKED` until those prerequisite profile/deployment proofs exist.

## Rollback

Revert this PR. Existing signer, sender, lifecycle, capital and MPR-2610 owners
are not migrated or replaced, so rollback must not delete durable attempts or
rewrite historical settlement evidence.
