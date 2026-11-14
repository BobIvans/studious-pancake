# Strategy expansion — coordinated agent assignments

Это отдельный strategy workstream. Он не дублирует market integration/P0 assignment и не должен менять файлы/owners, над которыми сейчас работают P0/MASTER agents, без согласования. Сначала refresh branch/PR/dependency state; затем распределить work packages.

## Coordination rules

1. Один coordinator обновляет crosswalk и dependency DAG; каждый agent получает один bounded package и один canonical owner.
2. Agents may work in parallel on independent docs/tests/adapters. Shared files (`strategies.py`, capabilities, graph, scheduler, `format_targets.txt`, verify scripts) имеют одного назначенного интегратора.
3. Не повторять уже существующие R10-A…I, WG-01…WG-28 и OP-01…OP-28. Эти задачи считаются исходными; ниже — новые acceptance/implementation layers и missing families.
4. Каждый package начинает с owner audit, exact external docs/license review и current-main diff. No duplicate abstraction.
5. No live signer/sender/borrow/submission, wallet creation or production promotion. PR only; no auto-merge.

## Work packages

### SX-00 — Main/PR and strategy assignment reconciliation (coordinator)
- Refresh main SHA, open/merged/closed PRs, current R10 lanes and all files listed in README.
- Build a machine-readable delta: existing family/task/owner vs missing acceptance vs truly new family.
- Mark each existing R10-A…I / WG / OP as KEEP, EXTEND, BLOCKED, DUPLICATE or RETIRED with evidence.
- Reconcile this pack with the active MASTER market-integration assignment without copying its task text or taking ownership of P0 work.
- Acceptance: every family has one canonical owner, one next task, one dependency, one status and no duplicate solver/registry.

### SX-01 — Canonical strategy contract and typed execution classes
- Map the contract in `STRATEGY_CATALOG_AND_EXECUTION_CLASSES_RU.md` to existing dataclasses/schema; do not create a second runtime registry.
- Ensure every strategy candidate carries identity, state generation, amount, resource manifest, execution class, cost ledger, proof and rejection reason.
- Extend schemas additively and maintain backward compatibility.
- Acceptance: contract round-trip, unknown fields fail closed, vector assets/claims conserved, all unproven fields remain null/UNKNOWN.

### SX-02 — Flash-mint and lender-selection economics
- Extend existing flash capital graph/provider governance owners to compare lender flashloan vs protocol flash-mint where available.
- Model caller eligibility, receiver/callback, fee, cap, asset, repayment, same-tx postcondition, source revision and capacity freshness.
- Compare provider options for each strategy/asset/amount; no TVL proxy and no assumption of free flash-mint.
- Acceptance: exact repayment and fee vectors, no cross-domain funding, provider unavailable/unknown blocks route.

### SX-03 — Curve LLAMMA and banded liquidation
- Research official Curve LLAMMA contract/whitepaper/SDK revision and current market/account state requirements.
- Add a protocol dossier and exact band/price/oracle/collateral transition replay in existing Curve/strategy owners.
- Integrate liquidation eligibility and collateral unwind only through shared exact evaluator.
- Acceptance: boundary vectors across band crossings, oracle movement, partial liquidation, fee and stale state; no constant-product approximation.

### SX-04 — OEV/oracle auction and keeper strategy
- Dossier oracle update auctions, OEV rights, keeper eligibility, auction payment, update ordering, liquidation impact and settlement.
- Treat oracle/reference value as signal; only protocol-specific authorized transaction can be an execution leg.
- Acceptance: event timeline replay, auction bid economics, no unauthorized data, no oracle price treated as executable quote.

### SX-05 — JIT LP / LVR / adverse-selection strategy pack
- Extend market-making owners with event-level JIT liquidity and LVR measurement; separate passive inventory from atomic transaction strategy.
- Measure fees, inventory delta, price markouts, volatility regime, range, gas/compute and withdrawal costs.
- Strictly exclude sandwich, frontrun, victim targeting and unauthorized private orderflow.
- Acceptance: replayed fill-to-markout, LVR decomposition, inventory/capital lock and baseline comparison; JIT not enabled without proven transaction rights.

### SX-06 — CLOB/RFQ/queue-aware market making
- Extend existing Phoenix/OpenBook/DeepBook/orderbook owners; no second book model.
- Model exact sequence/checksum, L2 depth, tick/lot, IOC, partial fill, maker/taker/rebate, queue uncertainty, cancel latency, quote TTL and adverse selection.
- RFQ firm quote and intent permission are separate capabilities.
- Acceptance: replayed fill/no-fill/partial/cancel cases; no quote-to-fill inference; resting inventory not flash-funded.

### SX-07 — Prediction-market complete sets and financial claims
- Add typed vector claims and conditional outcome settlement to existing hyperedge/rights owners.
- Research outcome completeness, mutually exclusive/exhaustive proofs, collateral, split/merge, fee, resolution oracle, dispute window and redemption.
- Acceptance: vector conservation and adversarial resolution cases; maturity/settlement waiting classified non-atomic.

### SX-08 — Lending rates, refinance and collateral optimizer
- Extend existing lending indexer, solvency and flash-capital owners.
- Separate intra-tx refinance/collateral swap from multi-period supply/borrow carry.
- Model utilization, borrow/supply APR, caps, eMode, liquidation threshold, oracle, collateral correlation, fees and stress.
- Acceptance: health factor after every transition, repayment proof, no double-counted collateral, time-series carry with funding/withdrawal risk.

### SX-09 — LP lifecycle and inventory/fee harvesting
- Model LP mint/burn/collect/compound/range shift, NFT/position rights, fee claim, IL, gas, inventory and capital lock.
- Reuse CLMM/DLMM math and existing strategy evolution/rights owners.
- Acceptance: exact position state and token conservation, markout/IL after fees, no assumption flashloan can finance persistent LP position.

### SX-10 — Permitted backrun, blockspace and transaction-ordering economics
- Research only public/authorized orderflow and protocol-permitted backrun/auction mechanisms; no sandwich/frontrun.
- Model pre/post state, inclusion probability calibration, priority fee/tip, compute, revert cost, competition, builder/validator/sequencer rights and realized settlement.
- Acceptance: deterministic auction replay and cost ledger; no sender/Jito enablement; no probability claims without observed calibration.

### SX-11 — Cross-rollup/shared-sequencer and async inventory
- Separate local atomic, shared-sequencer hypothesis, bridge/IBC, CEX settlement, TON async and prefunded rebalance.
- Model finality, message delivery, reorg, timeout, withdrawal, stranded inventory, hedge and capital lock.
- Acceptance: fault injection and settlement-state machine; no atomic classification without proof from protocol semantics and transaction boundary.

### SX-12 — Portfolio optimizer and multi-strategy conflict scheduler
- Extend AGG-05 conflict scheduler and shared execution state with strategy portfolio allocation.
- Optimize candidates across same snapshot with shared pools, lender capacity, collateral, account locks, inventory, compute and provider quotas.
- Compare single strategy, independent execution, joint split, batch clearing and portfolio baseline.
- Acceptance: 1/2/4/8 worker deterministic results; no resource double spend; finite-search bounds explicit; joint result improves after costs or is rejected.

### SX-13 — Strategy learning, causal evaluation and context bandit
- Extend existing decision dataset, ranker, correlation ledger and EVO-09; no second feature store/ledger.
- Add per-family null/control, time-blocked holdout, purged grouped split, embargo, provider/pool leakage controls, source ablation, multiple-testing correction and negative/no-trade corpus.
- Bandit can allocate research/read quota only; deterministic baseline remains.
- Acceptance: calibration, confidence intervals, sample counts, false positives/negatives, drift and reproducibility; model cannot bypass gates.

### SX-14 — Verifiable data/compute procurement and mechanism lab
- Extend existing INST-01 and Market-of-Markets owners.
- Define one verifiable task (decode, exact quote, replay), task hash, data rights, independent recomputation, latency/cost/accuracy and auction baseline.
- Mechanism lab compares fee/auction/allocation rules on fixed offline workload.
- Acceptance: no fabricated demand or payments, duplicate task idempotency, reproducible output and surplus ownership.

### SX-15 — Strategy portfolio observability and release matrix
- Extend existing telemetry, evidence bundle and paper qualification owners.
- Per-family dashboard: status, dependencies, sample size, exactness, capacity, net outcome, rejection/no-trade, resource conflicts, costs and holdout.
- Acceptance: no whole-universe coverage claim from one passing venue; each pack separately gated and rollbackable.

### SX-16 — Final strategy-pack integration and evidence reconciliation
- Coordinator-only final pass after the independent lanes return.
- Reconcile strategy IDs, owner paths, schemas, capability vocabulary and typed blockers into the existing crosswalk/registry owners; preserve original WG/OP/R10 IDs.
- Check no duplicate graph, solver, registry, ledger, journal, scheduler or capital authority was introduced; verify every family has an explicit status and next evidence gate.
- Acceptance: deterministic crosswalk validation, no unresolved ownership collision, per-family evidence bundle references and a truthful coverage report. No live promotion.

## Dependency and parallel execution plan

- SX-00 first as a short read-only coordinator gate.
- After SX-00, parallel lanes: SX-02 (capital), SX-03 (LLAMMA), SX-04 (OEV), SX-05/06 (liquidity/microstructure), SX-07 (claims), SX-08/09 (credit/LP), SX-10/11 (ordering/settlement), SX-13 (learning), SX-14 (mechanism lab). Each starts with docs/contract/tests; shared source owners require explicit file ownership.
- SX-01 is the common schema/integration lane; SX-12 depends on resource manifests from SX-01 plus existing AGG-05; SX-15 consumes evidence from all lanes.
- SX-16 integration/reconciliation is coordinator-only: reconcile adapters and family statuses into existing owners; do not change P0 market intake/quote assignment.
- Every lane may deliver BLOCKED with exact missing evidence. “Parallel” never means skipping dependencies or pretending missing integrations exist.

## Required PR report per package

- Base SHA and head SHA; changed paths; owner map; no overlap check against active PRs.
- External docs, version/hash/license; state/identity fixtures; tests and deterministic replay receipt.
- Strategy class and atomicity rationale; exact amount/capacity/fee/repayment proof or typed blocker.
- Resource conflicts and comparison to independent baseline.
- Positive, negative, stale, partial, rejected and no-trade examples.
- No live/sender/signer changes; rollback and next dependency.
