> **Archive reconciliation:** the V1/V3/V4/V4.1/V5/V6 Build Bigger Universe Graph work is now mapped in `BUILD_BIGGER_UNIVERSE_GRAPH_ARCHIVE_RECONCILIATION_RU.md` and assigned through `BUILD_BIGGER_UNIVERSE_GRAPH_WORKPACKAGES_V1.json`. The previous ten EXP families are only the incremental gaps, not the full recovered strategy universe.

# Strategy research crosswalk — что уже есть, что расширить, что действительно новое

**Snapshot:** main d52e61f36ece249c1221c8e71d22aa29ef476e21; PR #643 merged, #645 open for SX-12 at authoring. Исторические статусы не считать live: агент обновляет их до запуска.

## Метод и архивная полнота

Сверены PR #599, #622, #631, #637–#643, основной код/тесты, S01–S07, OP-01…OP-28, WG-01…WG-28, R10-A…I, SX-00…SX-16 и доступные сохранённые параллельные разговоры. Архив conversation captures не является полным экспортом всех диалогов, поэтому документ фиксирует только реально найденные темы. Агент должен продолжать искать идеи в доступном Library/repo history и добавлять их с доказательством, а не заявлять, что неизвестные чаты прочитаны полностью.

## Что уже существует — не переписывать

| Family | Canonical owner / PR | Реальное положение | Следующий шаг |
|---|---|---|---|
| Direct two-leg circular AMM | PR-033/056; strategies.py, detector | Один реальный two-leg shadow detector | Exact evaluator + R04/R05/R06 path |
| Size-curve/non-monotonic sizing | PR118, non_monotonic_sizing.py | Existing exact amount grid / economics | Fresh quote each amount; connect exact evaluator |
| Bounded 2–5 hop | arbitrage_graph.py, multihop_solver.py | Topology/shadow shortlist, not profit proof | Exact per-leg evaluator, shared-state replay |
| Split-flow/shared pool | split_flow.py, cpmm_split_replay.py, AGG-05 | Partial/offline, multi-resource closure incomplete | Extend across ticks/bins/books |
| Market relations/residuals | #614 relation_generators + CorrelationLedger | Seven residual families, aligned lead/lag; research signal only | Feed evidence to detectors, keep advisory |
| Stablecoin/issuer redemption | stable_peg + stable residual | Math/research exists, issuer redemption anchors missing | Source proof + exact venue edges |
| LST/LRT/NAV/instant exit | stake_queue, anchors/residuals, strategy shells | LST detectors STUB; exchange rate/instant exit unproven | R10-B detector follow-up; no duplicate |
| BTC wrappers, vault shares, Pendle | strategy_evolution rights_lifecycle/incentive_epoch | Research/partial; rights/maturity/exit proof missing | Keep in R10-D/B |
| Liquidation/health factor | lending_indexer, liquidation planner | Fixture/shadow only; capacity/rooted accounts/build/sim gates missing | R02/R03/R05 proof; monitor lane only |
| CLOB/AMM Phoenix/OpenBook/DeepBook | orderbook providers/planner | Fixture-gated; live subscriptions/depth/fill semantics not qualified | R07 subscription work; SX-06 economics only |
| CLMM/DLMM | P0-3 #613, native Raydium/Meteora decoders | Math/decoder work exists; graph-bound exact evaluator and rooted state remain | EXP-03 + R04/R05; do not duplicate decoders |
| Flash capital/provider selection | FlashCapitalGraph, R02 readers | Zero qualified capital edges at R10 audit; offline decode != live capacity | R02 offline replay + user-gated live proof |
| Flash-mint | evm_financing FlashMintAdapter bounded offline | Adapter exists; missing full eligibility/fee/cap/repay/capacity contract | SX-02 |
| LLAMMA | admission shells/stubs | No official band model/market dossier | SX-03 |
| OEV | no complete owner | Absent at SX-00 audit | SX-04 |
| JIT/LVR | partial concepts only | No complete event-level fills/markouts/inventory model | SX-05 |
| CLOB queue/RFQ market making | orderbook/intent owners | Partial; no calibrated queue/fill/rebate/cancel economics | SX-06 |
| Prediction complete sets | enum label | No outcome-vector conservation model | SX-07 |
| Lending rates/refinance | lending_indexer/solvency | Partial, no complete curve/atomic-vs-carry separation | SX-08 |
| LP lifecycle | #642 src/research/lp_lifecycle | Generic offline integer model; not venue-integrated; no fee-growth/NFT/state pins | Keep SX-09, add venue-specific proofs later |
| Backrun auction | #643 | Offline deterministic replay; no real orderflow/permissions/calibration | Keep SX-10; no new copy |
| Async settlement | #643 | Offline settlement state machine; no real bridge finality proof | Keep SX-11; SIGNAL_ONLY |
| Portfolio optimizer | #645 open at snapshot | Uses SX-01 ResourceManifest + AGG-05 resource semantics; one optimizer owner | Do not duplicate; review/merge #645 |
| Causal/learning/ranking | AGG-10, decision dataset, ranker, EVO-09 | Advisory only; holdout/leakage/negative corpus incomplete | SX-13 |
| Data/compute procurement | INST-01 / PR-359 | Partial canonical service | SX-14 extension, no second marketplace |

## Исторические темы из параллельных разговоров

Доступный сентябрьский strategy archive содержал: circular AMM arbitrage; size-curve opportunity; CLOB↔AMM; LST NAV/depeg; DBC migration; post-large-swap residual; Jupiter liquidation forecast; liquidation cascade; oracle↔DEX divergence; stablecoin peg triangles; CLMM/DLMM liquidity cliffs; Token-2022 transfer fee/hook mismatch. Также рассматривались robust Z/MAD/EWMA and velocity features, liquidity/depth changes, slot/quote age, protocol state anomalies, public MEV competition labels for crowding only, and opportunity survival. Не смешивать эти сигналы с исполняемыми quotes/capacity.

## Новые/недопокрытые work packages

1. **EXP-01 post-state dislocation:** confirmed large-swap/event → coherent state → residual → exact quote → first/last profitable time and survival. Not mempool sniping.
2. **EXP-02 DBC→DAMM lifecycle/migration:** curve segment, quote reserve/threshold, migration keeper/config, pre/post pool identity, Token-2022-aware transfer/fee. A predicted threshold is not proof of migrated market.
3. **EXP-03 liquidity cliff:** initialized CLMM ticks/DLMM bins, bitmap, consumed input, partial fill, dynamic fee and exact amount-dependent evaluation.
4. **EXP-04 Token-2022 economics:** epoch transfer fee, withheld amount, fee cap/rounding, transfer-hook program and extra-account metas; route-feasibility guard, not alpha.
5. **EXP-05 liquidation cascade:** public rooted position trajectories, health distance, collateral/debt, exact unwind, capacity and competition. Monitor only.
6. **EXP-06 protocol invariant anomaly:** versioned state transition contracts, conservation checks, explainable anomaly, false-positive/negative, held-out regime; advisory only.
7. **EXP-07 opportunity survival/crowding:** empirical first-seen/first-positive/last-positive/fill/revert/no-fill labels, censoring, latency and crowding calibration; public/authorized aggregate evidence only.
8. **EXP-08 intents/RFQ/CoW batch auction:** protocol-specific signed intent, Coincidence-of-Wants, solver competition, partial fill, fairness/surplus and EVM settlement; no Solana atomicity inference.
9. **EXP-09 derivatives/basis:** spot-perp/futures/options/funding, hedge, margin, liquidation, expiry and carry; non-atomic by default.
10. **EXP-10 Uniswap v4 Hooks:** hook permission bits, deployed bytecode, callback order, dynamic fee, hook/protocol/LP fee separation, custom accounting/TWAMM only when proven; per-hook dossier, no generic v3 formulas.

## Wave-6 Market Ecology — recovered research system

W6-00…W6-11 and W6F-001…W6F-096: participant archetypes; empirical population calibration; deterministic multi-agent market ecology; own-impact/feedback; benign competition and opportunity survival; bounded PSRO/self-play; mechanism/auction sandbox; co-adaptation and edge decay; sim-to-real reality gap; MCP/A2A research federation; evidence-aware knowledge distillation. Reuse existing simulator, causal twin and benchmarks. Synthetic data remains synthetic, remote agent artifacts require local replication. No remote authority or trade permissions.

## Protocol-source pins for the new lanes

- Meteora DBC developer guide and migration semantics: https://github.com/MeteoraAg/docs/blob/main/developer-guides/dbc/index.mdx
- Meteora DBC model overview: https://github.com/MeteoraAg/docs/blob/main/core-products/dbc/what-is-dbc.mdx
- Solana Token-2022 transfer fees: https://solana.com/docs/tokens/extensions/transfer-fees
- Solana Token-2022 transfer hooks: https://solana.com/docs/tokens/extensions/transfer-hook
- Uniswap v4 Hooks and dynamic fees: https://developers.uniswap.org/docs/get-started/concepts/hooks
- CoW intents and fair combinatorial auction: https://docs.cow.fi/cow-protocol/concepts/introduction/intents

At implementation start, re-fetch current official docs, record revision/hash/license and deployed identifiers. URLs are discovery pointers, not deployment/state proof.

## Classification / safety

- LOCAL_ATOMIC_CANDIDATE only where same-domain transaction boundary, exact quote, effective capital, build and complete simulation can be proven.
- CONDITIONAL_HYPEREDGE for issuer/vault/claim/collateral rights and callbacks.
- HEDGED_NON_ATOMIC for LP inventory, market-making, derivatives/carry unless a fully proven atomic recipe exists.
- SIGNAL_ONLY for oracle/DEX lead-lag, cross-chain/bridge/TON async, external references.
- CONTROL_PLANE for resource allocation and route feasibility.
- RESEARCH_ONLY for anomaly, learning, mechanism and ecology.
- EXCLUDED for user-prohibited/unauthorized mechanisms.

Unknown is never zero. No TVL-as-capacity, no quote extrapolation, no duplicate pool/collateral/lender/account/quota consumption, no unlicensed source reuse, no private keys or account creation, no signing/sending/borrowing/deploying/live trading, no tokenized equities, no sandwich/frontrun/user targeting/private-flow exploitation.



## Дополнение: широкая arbitrage map и data-source coverage (2026-11-14)

Проведён дополнительный аудит источников, нужных для подключения архивных стратегий к боту. Результат находится в:
- ARBITRAGE_MAP_STRATEGY_AND_DATA_SOURCE_ATLAS_RU.md
- ARBITRAGE_DATA_SOURCE_CATALOG_V1.json
- ARBITRAGE_MAP_DATA_SOURCE_ASSIGNMENTS_RU.md

### Новые пробелы не только в alpha, но и в наблюдаемости рынка

1. Нужен единый source-role map: raw chain state, direct venue state, quote router, oracle, CEX/perps, flash lender, bridge/claim, indexer и historical analytics — это разные типы данных и доказательств.
2. Нужна strategy-to-source coverage: каждая strategy family должна иметь источник обнаружения, canonical identity, exact state, exact amount quote, funding/build/simulation requirements и replay receipt.
3. Нельзя считать два aggregator quotes независимыми пулами, TVL flash capacity, CEX book локальной atomic liquidity, bridge flow atomic transfer, protocol SDK — deployed integration, а индексатор — source of truth для точного текущего состояния.
4. Большой cross-chain/market universe сохраняется. TON/Cosmos/CEX/perps/oracles/bridge data могут расширять radar и inventory strategies, даже когда не подходят к flashloan critical path.
5. Внешние условия изменяются: Balancer BIP-928 перевёл большинство pools в withdrawals-only с 2026-10-30; отдельные partner V3 pool exceptions требуют per-pool доказательства до 2026-11-30. DefiLlama free yield pools/chart endpoints отключены с 2026-11-13, GeckoTerminal high-rate on-chain access перешёл в Pro, Sui mainnet JSON-RPC отключён — новые reader-ы только на gRPC/GraphQL/checkpoints.

### Что осталось подключить

Выполнить DS-00…DS-11, но расширять текущих owners: P0-1/2/3, AssetResolver/DynamicUniverse, PAIR-00, direct_venue, R13-K, R02/R03, FlashCapitalGraph, PR118, AGG-05, StrategyContractV1, ExactSimulationFinalizer, paper/replay и W6. Не создавать вторые registry, graph, quote engine, source journal или execution kernel.
