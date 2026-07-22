# PR-194 — Proof-critical quota reservation and starvation-free scheduling

## Purpose

PR-194 closes the reproduced case where eight optional Jupiter discovery requests
fill the non-finalization capacity of a `limit=10, finalization_reserve=2` window,
yet the route scheduler returns `quota_exhausted` before planning the still-eligible
finalization request.

This change remains fail-closed and does not enable signing, submission, live funds
or unbounded provider probing.

## Active Jupiter correction

`JupiterRouteAttemptScheduler` now evaluates quota eligibility per attempt purpose.
When optional capacity is full:

- discovery and refinement profiles are skipped;
- finalization profiles remain eligible while their reserve is available;
- the plan is globally `quota_exhausted` only when every configured purpose is
  unavailable;
- skipped profiles are recorded with a stable reason.

Configuration validation requires at least one finalization profile and prevents
`reserve_finalization_profiles > max_attempts`. Optional profiles are truncated
before finalization profiles are appended, so `max_attempts` cannot silently remove
all proof-critical profiles.

`JupiterQuotaManager` exposes pure `capacity_for`, `available_for` and `can_reserve`
queries. Planning therefore does not spend or leak a reservation. Proof-critical
finalization, settlement/status and emergency reconciliation may use the protected
window reserve; unknown purposes fail into optional discovery.

## Fair workload scheduler

`BoundedFairWorkloadScheduler` adds a deterministic admission and dispatch boundary
for:

- optional discovery;
- required discovery;
- refinement;
- finalization;
- settlement/status;
- emergency reconciliation.

The scheduler provides:

- bounded total pending work;
- separate critical and required admission reserves;
- per-strategy caps;
- weighted fair virtual-finish tags by workload/strategy/provider lane;
- age and deadline pressure;
- rejection of expired or impossible-to-finish work before resource use;
- isolated discovery, finalization and settlement inflight pools;
- cancellation that releases pending or inflight ownership exactly once;
- wait percentile, fairness-share, rejection and critical-denial metrics;
- a cancellation-safe async waiter facade.

A high-priority noisy strategy cannot occupy every pending slot or the dedicated
finalization/settlement workers. Required low-volume work receives bounded service.

## Safety invariants

- live trading remains disabled;
- no signer or sender path is added;
- planning never consumes provider quota;
- optional work cannot consume critical queue reserve;
- discovery inflight exhaustion cannot block finalization or settlement pools;
- expired or deadline-infeasible work is rejected before dispatch;
- cancelled waiters do not create reservations or inflight leases.

## Verification

Focused tests cover:

- the reproduced discovery-cap/finalization-reserve case;
- finalization truncation by `max_attempts`;
- invalid configurations with no finalization guarantee;
- noisy-strategy flood and per-strategy isolation;
- required-work admission and aging/priority behavior;
- finalization and settlement during discovery saturation;
- expired and impossible work;
- pending/inflight cancellation;
- deterministic recorded workload order and fairness metrics;
- cancellation-safe async waiters.

## Remaining programme work

This PR provides the active scheduling primitives and Jupiter cutover. Sustained
provider-load evidence, connection-pool integration at every runtime composition
root, production SLO thresholds and the PR-160 long-running overload soak remain
separate operational evidence tasks.
