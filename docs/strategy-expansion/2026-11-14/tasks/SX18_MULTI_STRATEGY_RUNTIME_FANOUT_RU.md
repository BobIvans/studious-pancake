# SX-18 — Runtime multi-strategy fanout and evidence-gated composition

**Class:** CONTROL_PLANE / runtime composition.  
**Purpose:** connect the strategy catalog and typed contracts to a bounded, deterministic, concurrently evaluated strategy runtime using existing application owners. This closes the gap between “many strategy ideas or library modules” and “many independently qualified strategies evaluated concurrently against one coherent market state”.

## 0. Why this task exists

The current contract and research layers are not equivalent to a running strategy engine:
- `src/strategy/strategy_contract.py` (SX-01) is an immutable, fail-closed advisory schema. It does not provide a runtime registry or activation API.
- `src/strategy/strategies.py` currently declares six supported registrations. Only `CircularArbitrageStrategy` has a non-empty detector path (two-leg snapshot detection). LST detectors are stubs; liquidation/orderbook are disabled or quarantined shells; Pump migration is a boundary-only disabled adapter.
- `src/strategy/consumer.py` already provides the opportunity consumer/handler; supported paper/shadow composition has a sender-free consumer boundary.
- R08 audits (#624/#627) report 15/27 owner groups wired and 12 library-only. These are composition-audit receipts, not proof the complete multi-strategy fanout is already in the installed boot path.
- `src/strategy/conflict_scheduler.py` (AGG-05) is the conflict/scheduling owner. SX-12 (#645, merged) is the portfolio-selection extension. Neither should be duplicated.
- SX-17 is already assigned to archive detector/anomaly taxonomy reconciliation in #654. This task is deliberately **SX-18** to avoid ID collision.

Therefore, a catalog entry, contract object, detector class or unit test does NOT prove that the installed bot evaluates that strategy.

## 1. Required audit before implementation

Refresh current `main`, open PRs, CI and installed capability truth. Read:
- `src/application.py`, `src/strategy/strategies.py`, `src/strategy/registry.py`, `src/strategy/consumer.py`;
- queue/tracker/result sinks and the supported paper/shadow composition root;
- `src/strategy/strategy_contract.py` and `src/strategy/conflict_scheduler.py`;
- `src/runtime/core_v1_composition.py`, `src/runtime/core_v1_dependency_resolver.py`;
- `config/capabilities.json`, package resources and installed wheel manifests;
- `src/routing/route_graph.py`, durable reservation/lifecycle owners and AGG-05;
- R08 owner-injection reports, R10 strategy inventory/replay receipts, current MASTER00 matrix and SX-00 reconciliation;
- R04/R05/R06 acceptance and QPR/DIN admission contracts.

For every strategy registration and requested family, produce a matrix of:
1. canonical family / stable strategy ID;
2. implementation class and actual `detect_once` body;
3. source subscriptions and read owners;
4. snapshot generation and canonical asset/market identity inputs;
5. exact state/quote/economic evaluator;
6. execution class and typed blockers;
7. resource manifest and shared-resource conflicts;
8. reachability from supported application and installed package;
9. capability state and promotion tier;
10. tests/replay evidence and next dependency.

Do not mark a strategy runtime-reachable by importing a class in a test or adding a config row.

## 2. Runtime architecture — extend existing owners only

Use this shape after mapping each stage to the existing canonical owner:

```text
source receipts
  -> one immutable MarketSnapshotGeneration
  -> existing StrategyRegistry + installed capability policy
  -> bounded concurrent detector fanout
  -> StrategyContractV1 validation for each candidate
  -> shared exact evidence / quote / sizing path
  -> existing OpportunityQueue + OpportunityConsumer
  -> existing AGG-05 conflict/resource admission
  -> sender-free shadow outcome / existing paper gate
  -> immutable result + replay
```

Rules:
- **No second strategy registry, dispatcher, queue, consumer, scheduler, capital ledger, graph, sizing solver, market database, journal or release authority.**
- Reuse current `StrategyRegistry`, `build_application`, `OpportunityConsumer`, queue/tracker/result sinks, `StrategyContractV1`, `WorkResourceSet`, AGG-05, QPR/DIN governance and paper/shadow composition.
- Bind each work item to `(strategy_id, strategy_version, snapshot_generation, candidate_id, resource_manifest_hash, deadline, replay_id)`.
- All workers in one evaluation batch read the same immutable snapshot generation. No strategy may silently refresh a different leg/market generation or mutate shared state.
- Every candidate carries execution class, provenance, identity/state refs, exact quote requirements, `None` for unknown costs, ResourceManifest, risk flags, replay spec and typed no-trade/rejection reasons.
- Collect results in canonical deterministic order independent of worker completion order.
- Isolate each worker exception, timeout, cancellation or malformed candidate as a typed failure; unrelated strategies continue.
- Provider quotas remain in the existing provider-governance plane. Strategy CPU/queue budgets may be added only through an approved existing admission/config owner.
- AGG-05 remains the only conflict scheduler. SX-12 remains the portfolio optimizer; it consumes typed candidates/manifests after contract compatibility is proven.
- Shadow reservations are simulated/advisory only. They are not live capital rights.
- Output remains sender-free shadow/no-trade/blocked until R04/R05/R06 and runtime authority gates independently pass.

## 3. Work waves

### SX-18A — Contract-to-runtime adapter audit
Map StrategyContractV1 to actual Opportunity and runtime strategy interfaces. Identify the smallest additive adapter needed to preserve the contract through current candidate/consumer evidence without creating another registry. Produce contract tests and a current-vs-target composition graph.

### SX-18B — Bounded parallel detector fanout
Implement the narrow fanout extension at the existing application/registry/consumer seam:
- bounded worker count and per-run deadline;
- bounded queue/backpressure and explicit admission/rejection;
- deterministic result ordering and snapshot-generation binding;
- independent timeout/cancellation/failure isolation;
- duplicate idempotency and retry semantics;
- fairness so one high-volume strategy cannot starve others;
- immutable shared market input.

### SX-18C — Resource-aware candidate admission
Bind candidates to SX-01 ResourceManifest and AGG-05 WorkResourceSet. Ensure shared pool, tick/bin, book level, collateral, lender capacity, inventory, fee payer, nonce/object, account lock and quota cannot be jointly over-allocated. Reuse the existing reservation authority; add no other.

### SX-18D — Enable only real detectors, one at a time
- Existing circular two-leg detector remains the initial real detector until further detector bodies and tests are ready.
- R10-1 CPMM exact evaluator binding, R10-3 LST residual-fed detectors, R07 orderbook subscription qualification and EXP pilots each contribute their own contract/evidence.
- Disabled/fixture-only/Pump boundary strategies remain non-executable and may emit typed NOT_READY/BLOCKED status, never synthetic opportunities.
- Do not activate every catalog family simultaneously.

### SX-18E — Qualification integration
After evidence-specific routes are ready, route candidates through existing R04 route selector, R05 exact unsigned transaction/PTB simulator and R06 paper campaign. Runtime fanout cannot promote an execution class or skip a financing/source gate.

## 4. Mandatory acceptance tests

- Same immutable input generation with 1/2/4/8 workers produces identical candidate IDs, hashes, rejections and canonical order.
- Random worker completion order does not change results.
- Slow strategy, timeout, cancellation, exception, malformed contract and source outage are isolated; unaffected workers still return their own results.
- Queue saturation/backpressure is bounded and observable; no unbounded task creation.
- Duplicate candidate/replay ID is idempotent; stale generation and late result are rejected.
- Shared pool/book/tick/bin/lender/collateral/account/nonce/resource cannot be selected twice through AGG-05/SX-12.
- Every strategy result has explicit no-trade/rejected/blocked status; absence of opportunities is not evidence of data coverage.
- Unknown amount/cost/probability remains `None`; no default-to-zero.
- A strategy absent from installed supported composition is `LIBRARY_ONLY`, not runtime-enabled.
- Capability manifests, wheel resource manifests and runtime status commands agree.
- Focused suite, deterministic replay, type/format/security, package smoke and `scripts/verify_repo.py` pass on current supported Python 3.13 environment.

## 5. Dependencies and ownership

- SX-01 #641 merged: StrategyContractV1.
- SX-12 #645 merged: deterministic portfolio optimizer; consume it, do not recreate.
- R08 #624/#627 merged: consume its owner-injection map.
- R10-1/R10-2/R10-3 own CPMM, MarginFi capital and LST verticals; SX-18 coordinates runtime composition but does not reimplement those verticals.
- AGG-05 owns conflict admission. R04/R05/R06 remain downstream qualification gates.
- One coordinator owns shared edits to `src/application.py`, registry, strategy registration, capability manifests and package/resource verification. Other agents work only in disjoint adapters/tests until interfaces are frozen.

## 6. Acceptance is not production authorization

Passing SX-18 means independently proven strategy workers can be evaluated concurrently and safely produce evidence-bearing shadow candidates. It does NOT mean every strategy is implemented, enabled, profitable, paper-qualified, or backed by available capital.

No private keys, account/ATA/position/obligation creation, signing, sending, borrowing, spending, deployment, provider activation or production promotion. Keep live hard-denied.
