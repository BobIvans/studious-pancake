# MASTER execution roadmap — parallel work, dependency-gated integration

## Phase 0 — MASTER-00 (first task)
Reconcile V3/V4/V4.1/V5/V6/direct-venue archives, old parallel chat strategy deltas and current code/PR/CI. Produce pair delta, direct source coverage, strategy crosswalk, PR dependency map and owner/interface freeze. This is the only coordinator-owned first task. It is not a build-everything PR.

## Phase 1 — first implementation wave (parallel after interface freeze)
### A. Solana market-data P0 (three distinct agents)
- **P0-1:** safe indexed intake → Dynamic Universe. **Review and rebase existing open PR #593 first**; it is not merged. No duplicate implementation.
- **P0-2:** migrate existing quote owner from Jupiter V1 to V2, retain 0x, same canonical inputs/sizes, compare response data and replay. No parallel router.
- **P0-3:** finish exact venue-state readers. CPMM remains canonical; Raydium CLMM and Meteora DLMM get separate focused slices; Orca stays blocked pending legal approval.

### B. R-02 capital readers (four distinct read-only agents)
- CAP-A Jupiter Lend reserve and effective borrow capacity.
- CAP-B Kamino full reserve/market/fee/capacity decoder.
- CAP-C NAVI current package/config/pool objects via governed Sui gRPC/GraphQL.
- CAP-D Project 0 bank-only reader without wallet, optional pre-existing public account check only.
R-02 remains blocked with zero qualified edges until real resource-level evidence passes.

### C. R-03 unsigned builders (contract + protocol adapters)
- R03-00 freeze one canonical unsigned plan contract.
- Jupiter/Kamino/NAVI/P0 builders may work offline in isolated branches. A build fixture is not live capital capacity; R-03 can be built before R-02 finishes, but cannot be admitted to live-capital route selection without matching R-02 evidence.

### D. Whole-project research / platform / sources
- R09 Sui/TON/EVM/CEX/oracle/reference source research.
- R10 strategy crosswalk and evidence/replay experiments.
- R11 Windows/WSL, packaging, CI and offline reproducibility.
- R12 dependency-security remediation.
These independent lanes can work while P0/R02/R03 run, provided they do not edit common owner files concurrently.

## Phase 2 — integration freeze
One integration lead composes P0 market data, R02 capital readers, R03 builders and strategy candidate interfaces. Check all source generations, identities, venue resources, correlation groups and account-cost models. No duplicate capacity or pools when multiple routers quote one underlying source.

## Phase 3 — R04 capital-aware route selector
Enumerate `(strategy, route, settlement asset, lender resource, size)`. Requote each amount and all legs, bind same state generation, check independent resources, compute amount-dependent flash fee/rounding and all-in costs, use existing non-monotonic sizing and resource lock sets. The solver shortlist must be followed by the exact evaluator.

## Phase 4 — R05 complete exact atomic simulation
Assemble complete unsigned Solana message/Sui PTB/EVM transaction model, account/object dependencies, borrow/swap/repay order, callbacks/hot-potato receipt, gas/compute/rent/ATA/receiver costs, state freshness and postconditions. Only same-chain/same-domain routes can be local flash candidates. Bridge routes remain asynchronous signal/rebalance work.

## Phase 5 — R06 durable paper qualification
Run only after QPR source readiness + R04 exact route + R05 complete simulation. Record all positive, negative and no-trade outcomes, deterministic replay, false-positive rate, stability, costs, source ablation and holdout statistics. A 24/72h window is not evidence of profitable future trading by itself.

## Phase 6 — R07 incremental provider/venue expansion
Research can happen throughout. Implement one provider/venue per reviewable PR. Require deployment/ABI license proof, exact state/quote/capacity, source quota, full builder, simulation, and incremental route utility. Aggregators are route providers, not independent pools. All 27 flash candidates remain disabled unless independently qualified.

## Concurrency rules
- GLM 5.3 Flash may be used as a high-throughput agent, but token allocation is not permission for unconstrained parallel commits.
- Start one coordinator and up to the number of independent workers the coding harness/repository can safely support; practical target 4–8, not a hard requirement. One isolated worktree/branch per task.
- One agent owns a canonical file surface. Multiple agents may prepare research/fixtures against a frozen interface; shared owner changes are serialized.
- Each code worker opens a focused PR to current main; coordinator merges only after tests, evidence and human approval.
