# SX-17 — Runtime multi-strategy fanout and evidence-gated composition

**Class:** CONTROL_PLANE / runtime composition.  
**Purpose:** turn the existing strategy catalog and typed strategy contracts into a bounded, deterministic, concurrently evaluated strategy runtime that reuses the supported application owners. This is the missing bridge between “many strategies researched or implemented as libraries” and “many strategies safely evaluated against one market snapshot”.

## 0. Why this task exists

The current strategy contract and research layers are not the same thing as a running strategy engine:
- src/strategy/strategy_contract.py (SX-01) is an immutable, fail-closed advisory schema and explicitly does not provide a runtime registry or activation API.
- src/strategy/strategies.py currently declares six supported strategy registrations. Only CircularArbitrageStrategy has a non-empty detector path (two-leg snapshot detection). LSTDepegStrategy and LSTUnstakeStrategy are disabled stubs; liquidation and orderbook are disabled/quarantined shells; Pump migration is a boundary-only disabled adapter.
- src/strategy/consumer.py already provides the opportunity consumer/handler, and the supported paper/shadow application has a sender-free consumer boundary.
- R08 audits (#624/#627) report 15/27 owner groups wired and 12 library-only, with an eight-step composition plan. Those are audit receipts, not proof the complete multi-strategy fanout is already in the installed boot path.
- src/strategy/conflict_scheduler.py (AGG-05) is the conflict/scheduling owner. SX-12 (#645, currently open at this snapshot) is the portfolio-selection extension. Neither should be duplicated.

Therefore, an entry in the strategy catalog, a contract object, a detector class, or a unit test does NOT prove the installed bot evaluates that strategy.

## 1. Required audit before implementation

Refresh current main, open PRs, CI and package capability truth. Read:
- src/application.py and src/strategy/strategies.py;
- src/strategy/registry.py, src/strategy/consumer.py, queue/tracker/result owners;
- src/strategy/strategy_contract.py;
- src/runtime/core_v1_composition.py, src/runtime/core_v1_dependency_resolver.py;
- config/capabilities.json and installed package resource manifests;
- src/strategy/conflict_scheduler.py, src/routing/route_graph.py, durable reservation/lifecycle owners;
- R08 owner-injection reports, R10 strategy inventory/replay receipts, current MASTER00 matrix and SX-00 reconciliation;
- R04/R05/R06 acceptance and QPR/DIN admission contracts.

Produce a matrix for every existing strategy registration and each newly requested strategy:
1. catalog family / stable strategy ID;
2. implementation class and detect_once body;
3. actual source subscriptions/read owners;
4. snapshot generation and canonical asset/market identity inputs;
5. quote/exact-state/economic evaluator;
6. execution class and typed blockers;
7. resource manifest and shared-resource conflicts;
8. supported application/installed-package reachability;
9. current capability and promotion tier;
10. tests/replay receipt and next dependency.

Do not mark a strategy runtime-reachable by importing a class in a test or by adding a config row.

## 2. Runtime architecture — extend existing owners only

Use the following shape; map each step to its existing canonical owner before editing:

Source receipts -> one immutable MarketSnapshotGeneration -> existing StrategyRegistry/capability policy -> bounded concurrent detector fanout -> per-strategy candidate + StrategyContractV1 validation -> common exact evidence/quote/sizing path -> OpportunityQueue + existing OpportunityConsumer -> existing AGG-05 resource conflict/admission owner -> sender-free shadow outcome / existing paper gate -> immutable result + replay.

Rules:
- No second strategy registry, dispatcher, queue, consumer, scheduler, capital ledger, graph, sizing solver, market DB, journal or release authority.
- Reuse StrategyRegistry, current build_application, OpportunityConsumer, existing queue/tracker/result sinks, StrategyContractV1, WorkResourceSet, AGG-05, QPR/DIN source governance and the current paper/shadow composition root.
- Each work item is bound to (strategy_id, strategy_version, snapshot_generation, candidate_id, resource_manifest_hash, deadline, replay_id).
- All strategy workers read the same immutable snapshot generation for one evaluation batch. A worker may not silently refresh a different leg/market generation.
- Every candidate carries typed execution class, source provenance, identity/state references, exact quote requirement, None for unknown costs, ResourceManifest, risk flags, replay spec and no-trade/rejection reasons.
- Results are collected in deterministic canonical order independent of worker completion order.
- One worker's exception, timeout or malformed candidate is isolated and becomes a typed failure; it cannot terminate unrelated strategies or convert a failure into an empty successful market.
- Per-provider source quotas stay in the existing provider-governance plane. Per-strategy CPU/queue budgets may be added only through an approved existing admission/config owner.
- AGG-05 is the only conflict scheduler. SX-12 is the portfolio optimizer; it receives typed candidates/manifests only after the current owner contract is frozen.
- Shadow reservations are simulated/advisory only. No reservation or allocation is a live capital right.
- The output remains sender-free SHADOW_NOT_EXECUTED/blocked/no-trade until the existing R04/R05/R06 and runtime authority gates independently pass.

## 3. Work waves

### SX-17A — Contract-to-runtime adapter audit (can start immediately)
Map StrategyContractV1 to actual Opportunity and runtime strategy interfaces. Identify the smallest additive adapter needed to carry the contract through current candidate/consumer evidence without creating a second registry. Write contract tests and an explicit current-vs-target composition graph.

### SX-17B — Bounded parallel detector fanout
Implement the narrow fanout extension at the existing application/registry/consumer seam:
- bounded worker count and per-run deadline;
- bounded queue/backpressure and explicit admission/rejection;
- deterministic result ordering and snapshot-generation binding;
- independent timeout/cancellation/failure isolation;
- duplicate idempotency and retry semantics;
- fairness so one high-volume strategy cannot starve others;
- no strategy may edit or mutate the shared snapshot.

### SX-17C — Resource-aware candidate admission
Bind candidates to the SX-01 ResourceManifest and AGG-05 WorkResourceSet. Ensure shared pool, tick/bin, book level, collateral, lender capacity, inventory, fee payer, nonce/object, account lock and quota resources cannot be jointly over-allocated. Reuse the existing reservation authority; do not add another.

### SX-17D — Enable only real detectors, one by one
- Existing circular two-leg detector remains the only initial detector in the supported path until more detectors have bodies and tests.
- R10-1 CPMM exact evaluator binding, R10-3 LST residual-fed detectors, R07 orderbook subscription qualification, EXP detector pilots and SX strategy models each contribute their own explicit contract/evidence.
- Disabled/fixture-only/PUMP boundary strategies must remain non-executable and may produce typed NOT_READY/BLOCKED states, never synthetic opportunities.
- Do not switch on every catalogue family simultaneously.

### SX-17E — Qualification integration (dependency-gated)
After evidence-specific routes are ready, pass candidates through existing R04 route selector, R05 exact unsigned transaction/PTB simulator and R06 paper campaign. The runtime fanout itself cannot promote an execution class or skip a financing/source gate.

## 4. Mandatory acceptance tests

- Same immutable input generation with 1/2/4/8 workers produces identical candidate IDs, hashes, rejections and final canonical order.
- Randomized worker completion order does not change results.
- Slow strategy deadline, cancelled worker, exception, malformed contract and source outage are isolated; unaffected strategies still return their independent results.
- Queue saturation/backpressure is bounded and visible; no unbounded task creation.
- Duplicate candidate/replay ID is idempotent; stale generation and late result are rejected.
- Same pool/book/tick/bin/lender/collateral/account/nonce/resource cannot be selected twice through AGG-05/SX-12.
- Every strategy result has an explicit no-trade/rejected/blocked result; absence of opportunities is not treated as evidence coverage.
- Unknown amounts/costs/probabilities remain None; no numeric zero defaults.
- A strategy class absent from the installed supported composition is reported LIBRARY_ONLY, not runtime enabled.
- Capability manifests, wheel resource manifests and runtime status commands remain consistent.
- Full focused suite, deterministic offline replay, type/format/security, package smoke and scripts/verify_repo.py pass on current Python 3.13 environment.

## 5. Dependencies and parallel ownership

- SX-01 #641 merged: typed StrategyContractV1 is available.
- R08 #624/#627 merged: consume its owner-injection map; do not rerun the entire audit or wire every one of the 27 groups without proof.
- R10-1/R10-2/R10-3 own exact CPMM, MarginFi edge and LST detector verticals respectively; SX-17 coordinates their registered composition, it does not reimplement detectors.
- AGG-05 owns conflict admission; SX-12 owns portfolio optimization if #645 is reviewed/merged.
- R04/R05/R06 remain downstream qualification gates.
- One coordinator owns shared edits to src/application.py, src/strategy/registry.py, src/strategy/strategies.py, capability manifests and package/resource verification. Other agents work only in disjoint adapters/tests until interfaces are frozen.

## 6. Acceptance is not production authorization

Passing SX-17 means that several independently proven strategy workers can be evaluated concurrently and safely produce evidence-bearing shadow candidates. It does NOT mean that strategies are profitable, all are enabled, capital is available, paper qualification passed, or live execution is authorized.

No private keys, account/ATA/position/obligation creation, signing, sending, borrowing, spending, deployments, provider enablement or production promotion. Keep live hard-denied.
