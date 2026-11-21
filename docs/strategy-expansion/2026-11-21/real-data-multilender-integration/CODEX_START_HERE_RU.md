# Реальные данные → сравнение маршрутов → multi-lender flashloan → unsigned atomic build

**Дата аудита:** 2026-11-21  
**Цель:** довести уже существующие market, quote, flash-capital и builder owners до одного проверяемого evidence path. Это исполнительное задание для coding agent, а не ещё одна архитектура с новыми параллельными подсистемами.

## 1. Главный вывод аудита

В репозитории уже много нужных кирпичей, но это НЕ единый работающий путь от mainnet котировки к собранному flashloan:

- Solana: есть market discovery, exact-state owners и маршруты Jupiter/0x с разными уровнями wiring; PR #660 теперь merged и добавил CLMM/DLMM расширения. pmm-sim в PR #665 остаётся offline LiteSVM исследованием. Benchmark matrix ещё не выполнен.
- Sui: есть checkpoint/state discovery, модели NAVI/DeepBook financing и NAVI unsigned PTB builder. Есть offline Aftermath quote normalizer. Но Sui quote/PTB race ещё не подключён в supported runtime; Aftermath normalizer не имеет transport и boot-path wiring. Другие Sui routers пока в основном только source dossiers.
- Flash capital: FlashCapitalGraph, R02 readers и R03 unsigned builders уже существуют, но положительные live-qualified capital edges не доказаны. Документация/SDK discovery не доказывает текущую ёмкость конкретного lender.
- Execution: R03 BUILT_OFFLINE_UNQUALIFIED не означает готовый к исполнению план. Нужны qualified capacity (R02), exact full-message/PTB simulation (R05) и paper/qualification gates (R06/QPR). Не создавать обход этих ворот.

**Следовательно:** не нужно ещё одно сканирующее приложение, quote kernel, graph, capital graph, scheduler, transaction builder или RPC client. Нужно реализовать недостающие связи между существующими owners и добавить тесты.

## 2. Что агент должен переиспользовать

Перед изменениями повторно прочитать текущие версии этих owners и AGENTS.md, открытые PR, branch/worktree ownership:

| Задача | Canonical owner — расширять, не дублировать |
|---|---|
| Asset identity / Sui coin types / dynamic universe | docs/roadmap/dynamic-universe-master-2026-10-07/CODEX_START_HERE.md, существующие AssetIdentity/registry/resolver owners |
| Sui state, checkpoints, object provenance | src/gpr_sui_shadow/, governed QPR/DIN-02 read paths |
| Sui protocol state + PTB/hot-potato model | src/multichain/sui.py |
| Shared quote normalization, quote comparison, pool dedup | src/execution/quote_build_kernel.py (frozen contract); действующие R13 provider owners |
| Solana quote/discovery | src/solana_parallel_radar/, src/routing/, src/runtime_discovery_* |
| Flash lender registry/capacity economics | src/economics/flash_capital_graph/, existing R02 provider readers |
| Unsigned financing/build plans | src/lending/unsigned_builders/, src/lending/financing.py contracts |
| Exact transaction/PTB simulation | existing R05 ExactSimulationFinalizer owner; не подменять упрощённой swap quote |
| Paper/qualification evidence | existing R06/QPR/VerificationQueue/evidence owners |
| Concurrency / resource locks | SX-12 ConflictScheduler, PR #657 SX-18 StrategyRegistry/OpportunityConsumer (координировать; не добавлять второй orchestrator) |
| Signing / sending boundary | MPR-04/MPR-05 + PR130 existing sender policy; не менять в этом scope |

Read and reconcile these related handoffs on current main before coding: PR #664 data-campaign pack, PR #665 Prop-AMM research pack, PR #666 repository-knowledge context pack, R13 task docs/roadmap/agent-execution-master-2026-11-13/tasks/R13_MULTIPROVIDER_QUOTES_AND_BUILDS.md, R02/R03 assignments and PR #660 merged diff. These packs overlap in purpose but do not authorize activation.

## 3. Required end-to-end behaviour

The supported path must become:

1. Resolve exact chain + canonical mint/Move CoinType; discover actual pools/books and venue/program identity.
2. Capture immutable state with source/operator/correlation identity, slot/checkpoint, object version/digest, observed/available times and raw payload hash. Preserve source disagreement and negative outcomes.
3. Query independent quote providers at the exact same input/output representations, exact base-unit amount and bounded time skew. Preserve all winning and losing responses.
4. Deduplicate aggregator route legs by underlying pool/book/package/object lineage. Two aggregators quoting the same pool are correlated views, not extra liquidity.
5. Requote every candidate amount. Never scale a quote, marginal rate, TVL or indexer price into executable output.
6. Enumerate eligible flash-capital providers for the exact chain, borrowed CoinType/mint and requested amount. Require current enabled status, capacity, fee/rounding, constraints, source generation and freshness. Unknown values block; never default to zero.
7. Compare net economics including flash fee, swap/LP/aggregator/partner fees, gas/compute, rent/object setup, price impact, slippage reserve and delivery cost where applicable.
8. For the selected route, produce only an **unsigned** plan:
   - Solana: one atomic transaction, borrow → route instructions → exact output guard → repay.
   - Sui: one atomic PTB, borrow → composable swap PTB commands → repay exact hot-potato receipt.
   Cross-chain atomicity is NOT assumed. Do not split one flashloan across independent transactions.
9. Run full exact-message/PTB simulation against compatible current state and assert repayment, object/account closure, minimum output and positive all-in net outcome.
10. Persist a deterministic paper/evidence receipt. Status must distinguish DISCOVERY_ONLY, STATE_VERIFIED, QUOTE_COMPARABLE, CAPITAL_QUALIFIED, UNSIGNED_BUILT, SIMULATED and PAPER_QUALIFIED. Do not collapse them into one PASS.

A quote that beats another quote does not by itself tell the bot which lender to use. Lender choice is a separate per-asset/per-amount optimization step using current lender state and fees.

## 4. Provider priorities

Use SUI_ASSET_AND_PAIR_PLAN_RU.md and FLASH_CAPITAL_PROVIDER_MATRIX_V1.json. Main initial priorities:

- **Solana quotes/venues:** existing Jupiter V2, 0x and routing plane; direct exact-state venues already worked through CPMM/CLMM/DLMM owners; Prop-AMM routes via genuine official router/API/build surfaces. pmm-sim remains a local caller-sensitivity harness, never a mainnet identity switch.
- **Sui state:** governed gRPC and/or GraphQL profiles; two independently operated, non-smoke profiles for checkpoint/object consensus.
- **Sui quotes:** Aftermath, Cetus Aggregator V3, 7K/Bluefin7K, FlowX, OKX DEX, Rango and direct DeepBook. Implement one by one according to source/schema/license/auth/quota completeness. Never count an aggregator as an independent pool.
- **Solana lenders:** Kamino and Jupiter Lend first; Project 0 only when a valid existing public account context is supplied. MarginFi remains quarantined until its own blockers are closed.
- **Sui lenders:** NAVI and DeepBook first; Scallop and Bucket are additional candidates with protocol-specific limitations. Do not turn Cetus, Aftermath or FlowX into lenders: they are market/route sources in the reviewed evidence. Suilend remains research-only absent a proven public general-purpose flashloan surface.

Do not interpret a seed token as a market pair or lender asset. The agent must dynamically discover supported pools and ask the lender readers for exact capacities. See the Sui pair plan.

## 5. Capture/activation boundary

Implement bounded, restartable, read-only capture code and deterministic offline replay. Live capture stays disabled by default and must use the existing campaign/provider governance and operator-supplied profiles. Do not weaken the hard-block in src/gpr_sui_shadow/providers/__init__.py or bypass R02/QPR. A provider cannot become live-qualified merely because an API key or URL exists.

No wallet generation, account/ATA/object creation, signing, send, borrowing, spend, deployment, transaction submission, relay activation or production promotion in this assignment. Agent deliverable ends at reproducible data, qualified offline/authorized read evidence, unsigned plan and exact simulation result.

## 6. Deliverables

Coding agent must add actual implementation to an implementation branch/PR (not return only another plan):
- bounded read-only capture/ingress using existing state owners;
- Sui quote provider adapters and boot/funnel wiring to the existing R13 kernel, one provider at a time;
- pool lineage intersection dedup and exact-amount quote race;
- R02 lender selection inputs for Solana + Sui, with current evidence and typed blockers;
- conversion from selected quote + selected lender to existing R03 unsigned build plans, without duplicate builders;
- R05 full simulation composition or a precise blocked handoff to its owner;
- fixture replay, tests, metrics, rejection report and updated owner/knowledge maps.

Do not claim any source is live, any provider qualified, or any route profitable without actual evidence. If scope cannot be finished in one PR, deliver a vertical slice with working offline/replay path and typed blockers, then split per owner with dependency links.