# Strategy research expansion addendum v2 — parallel-chat reconciliation

Дата: 2026-11-14  
База репозитория: main@03b80389dd6d30d0c6eb7124b4bddb8d2e518aec  
Назначение: расширить merged Strategy Expansion #637 после SX-00 #639, не переписывая исходные SX-01…SX-16 и не дублируя market-integration owners.

## 0. Главный вывод

Предыдущего списка SX-01…SX-16 недостаточно, чтобы утверждать, что все стратегии из доступных параллельных обсуждений покрыты исполнительными заданиями. В архивных обсуждениях обнаружены отдельные механизмы, которые нельзя сводить к стандартному flashloan arbitrage:

1. DEX-native flash swaps / flash accounting / unlock-settle — внутренние обязательства DEX, а не lender flash loan.
2. Collateral-first liquidation и pre-liquidation callback, где collateral может поступить до закрытия долга и отдельный flash loan может не потребоваться.
3. Credit-conditioned DEX liquidity — доступная глубина и цена AMM зависят от разрешённого borrowing capacity и кредитного состояния.
4. Derivatives basis, funding, term structure и options parity — отдельные маржинальные/inventory стратегии, обычно не atomic flashloan legs.
5. Inventory-aware OMS и cross-venue market making — не только очередь ордеров, но и портфель открытых позиций, hedge и inventory skew.
6. Public trader/bot archetype intelligence — анализ публичных on-chain fingerprints и репозиториев как исследовательских признаков, а не копирование чужих сделок или объявление адресов прибыльными.
7. Token/protocol lifecycle events — unlocks, emissions, incentives, listings, migrations, governance и параметрические обновления.
8. Chain/data admission — измеримый выбор новых сетей и параллельных исторических/оперативных datasets.
9. Opportunity half-life и competition-aware execution research — измерять, как opportunity decays между detection, quote, simulation и возможной inclusion.

Эти пункты добавляются как SX-17…SX-25. Они расширяют, но не заменяют исходные SX-01…SX-16, S01–S07, OP-01…OP-28, WG-01…WG-28 и R10-A…I.

**Важное ограничение:** выполнение всех документных задач не гарантирует обнаружение прибыльных сделок, доступную ликвидность, внешние разрешения, live qualification или production readiness. Definition of Done — проверяемые owners, протоколы, модели, tests, replay и честные статусы/блокеры. Торговая активация остаётся отдельным процессом.

## 1. Что уже есть в main — не повторять

Состояние сверено по merged PR и SX-00 reconciliation:

| Существующая база | Что уже находится в main | Остаток |
|---|---|---|
| #599 MASTER-00 | V3–V6 strategy atlas, pair/source crosswalk, owner map, parallel assignments | Обновлять по актуальному SHA, не создавать новый atlas/registry |
| #622 + #631 R10 | 13 brief families, 6 runtime registrations, 12 relation kinds, 7 residual families, offline replay и typed blockers | Реализовывать только остатки; replay показал, что shortlist не равен net profit |
| #637 + #639 | SX-01…SX-16, gap analysis, acceptance matrix, SX-00 map и owner/dependency reconciliation | Добавить SX-17…SX-25, не повторять SX-00 |
| #638 R13-K | NormalizedProviderQuote, QuoteRace, pool/lineage dedup, BuildHandoff, запрет amount extrapolation | Переиспользовать; не создавать второй quote kernel |
| #640 R14-K | Unsigned Kamino financing plans как references внутри существующего planner; build/capacity статусы разделены | Не переписывать Kamino planner wiring; capacity всё ещё требует отдельного доказательства |
| #614 | Relation generators, correlation provenance и residual families | Расширять существующий relation/correlation owner |
| #498 AGG-05 | Parallel strategy conflict scheduler, bounded multihop, joint split-flow | SX-12/SX-21/SX-25 потребляют существующий scheduler |
| #500, #541, #542 | Decision intelligence, lifecycle/world model/VOI, relation science и experiment fabric | SX-22/SX-25 дополняют данными и measurement, не создают второй feature store или research DAG |
| #531–#537 | Strategy evolution, mechanism discovery и corrective semantic coverage | Использовать существующие strategy-evolution owners, не делать вторую систему |
| #613 + #634 | Raydium CLMM / Meteora DLMM decoders и math + проверка LEN | Graph exact-evaluator binding и rooted live state остаются отдельными gates |
| #618 + #621 + #630 + #635 | EVM/Sui/TON source dossiers и provider research | Dossier не равен adapter, current state, capacity, quote или atomicity proof |

### Runtime truth, а не размер research universe

SX-00 (#639) на момент аудита 5769b074 зафиксировал шесть registrations: только circular arbitrage имел реальный two-leg shadow detector; LST были stubs; liquidation и orderbook — fixture-only/quarantined; Pump — boundary-only. PR #640 добавил безопасную Kamino planner-reference wiring, но не превратил Kamino в qualified lender или liquidation strategy.

R10 ranked shortlist items 1–3 принадлежат прежним owners:
- CPMM exact evaluator → bounded-cycle paper path — R04/R06;
- MarginFi offline FlashCapitalEdge qualification — R02-CAP;
- LST residual-fed shadow detector bodies — R10 follow-up.

Не переносить эти задания в SX-17…SX-25 под новыми названиями.

R02 остаётся отдельным доказательным gate: reader или unsigned builder не доказывает эффективную flash capacity. Пока ресурсная capacity не подтверждена, сохраняется UNKNOWN и provider остаётся disabled.

## 2. Новые families SX-17…SX-25

### SX-17 — DEX-native flash swaps, flash accounting and internal settlement

**Почему добавлено:** lender flash loan, protocol flash-mint и DEX-native flash accounting — разные liabilities и callbacks. Например, Uniswap v4 PoolManager использует unlock/callback, после операций требует разрешить все balance deltas; неразрешённый delta приводит к revert. Это нельзя моделировать как универсальный borrow → swap → repay.

**Исследовать:** Uniswap v4 unlock/settle, Balancer V3 unlock/sendTo/settle и Ekubo lock/flash-accounting — только после pin официального deployment, revision, ABI и licence.

**Acceptance:** typed liability/delta manifest; callback caller authentication; exact settlement ordering; token conservation; все outstanding deltas = 0 до выхода; stale state, missing settle, wrong pool, wrong callback и overflow дают typed rejection; differential/golden vectors против pinned source. Отдельно измерять, когда внутренний netting сокращает transfers/fees. Не списывать повторно fees, уже embedded в quote output.

**Класс:** CONDITIONAL_HYPEREDGE; переход в LOCAL_ATOMIC_CANDIDATE только для конкретного доказанного deployment и одной transaction boundary.

### SX-18 — Collateral-first settlement and pre-liquidation callbacks

**Почему добавлено:** у отдельных протоколов collateral/auction callback может передать залог до завершения debt payment. Morpho pre-liquidation описывает onPreLiquidate после передачи collateral и до repayment; Sky Clipper liquidation допускает внешний callee callback во время collateral take и последующий расчёт DAI. Это может убрать отдельный lender flash loan, но только в рамках протокольных прав и точного порядка операций.

**Исследовать:** Morpho pre-liquidation, Sky Liquidation 2.0 / ClipperCallee, protocol-specific auctions и liquidation callbacks. Не обобщать semantics одного протокола на другой.

**Acceptance:** exact event/trace order; collateral transfer proof; caller/auction/liquidator eligibility; amount owed, fees, auction discount and callback authorization; repayment/settlement postcondition; rollback vectors; защита от reentry/stale auction/underflow; exact sale/exit quote и all costs. Отдельное сравнение: collateral-first vs external flashloan-funded liquidation.

**Класс:** CONDITIONAL_HYPEREDGE; это не универсальный liquidation bot и не доказательство отсутствия собственных gas/capital requirements.

### SX-19 — Credit-conditioned liquidity and lender-aware AMM execution

**Почему добавлено:** кредитная ликвидность может влиять на доступную глубину/цену AMM. EulerSwap-like JIT credit liquidity зависит от vault assets, borrowing rights, credit limits, collateral, utilization и caller restrictions. AMM spot reserves отдельно не описывают такую сделку.

**Acceptance:** jointly bind pool state + lender/vault state + borrower identity/eligibility + debt capacity + exact callback/settlement; проверить, что один capital/pool resource не используется дважды; смоделировать adverse credit-state change и cap exhaustion; вычислить exact all-in cost и repayment; сравнить со standalone AMM и standalone lender paths.

**Класс:** CONDITIONAL_HYPEREDGE до доказательства exact credit+swap contract. Использовать R13-K pool identity dedup и FlashCapitalGraph; не создавать параллельный credit registry.

### SX-20 — Derivatives basis, funding, term structure and options relationships

**Families:** spot/perpetual basis; funding capture; futures calendar/roll spreads; options put-call parity; synthetic futures; volatility surface/skew/calendar spreads; cross-venue derivatives basis.

**Почему отдельно:** derivative strategies требуют margin, collateral и holding horizon; hourly funding payment или expiry payoff не погашает same-transaction flash loan. Маршрут через несколько ног/площадок требует fill/hedge risk, а не фиктивного atomic swap graph.

**Acceptance:** canonical instrument identity, contract multiplier, inverse/linear payoff, quote currency, expiry, funding timestamp/rate, mark/index/oracle distinction, margin and maintenance rules, settlement currency, partial-fill/hedge state, borrow/funding costs; time-aligned replay, stress и out-of-sample holdout. Отделить basis signal от hedgeable executable order plan.

**Класс:** HEDGED_NON_ATOMIC / SIGNAL_ONLY по умолчанию. Любой действительно atomic protocol-specific sub-path доказывает собственные transaction semantics.

### SX-21 — Inventory-aware OMS and cross-venue market making

**Добавляет к SX-06:** portfolio/inventory layer для CLOB, RFQ, passive quotes и AMM liquidity. Требуется покрыть multi-venue inventory, quote skew, position limits, hedge routing, partial fills, cancels, stale orders, maker rebates, fee tiers, inventory markout, capital lock и venue outages.

**Acceptance:** replay event-by-event order lifecycle; различать quote, acknowledgement, fill, partial fill, cancel request и cancel confirmation; консервативно учитывать uncertain queue position; reconcile inventory per asset and venue; hedge residual exposure; test limit breaches and worker restart; сравнить net outcome с taker и no-trade baselines.

**Класс:** HEDGED_NON_ATOMIC. Resting inventory и delayed hedge нельзя представлять как flash-loan-financed atomic legs.

### SX-22 — Public trader/bot archetype intelligence

**Цель:** изучать implementation patterns и публичные execution fingerprints, а не копировать приватные стратегии или считать часто активный адрес прибыльным.

**Research corpus:** public GitHub strategy implementations, official protocol examples, academic taxonomies, legally reusable public chain transaction data и operator-owned bot episodes. Сравнивать route families, instruction composition, venues, fee/tip choices, timing, failure/revert frequency и observable execution pipeline patterns.

**Acceptance:** разделить code-derived archetypes и address-derived patterns; audit data source/licence/ToS/retention; pseudonymous identifiers and purpose limitation; selection-bias controls; transaction cost/failed attempt accounting; no profitability claim without reliable realized PnL and relevant capital basis; no deanonymization, profiling of private persons, unauthorized surveillance или private-orderflow access. Использовать #541/#542 и existing decision/replay/evidence owners.

**Класс:** RESEARCH_ONLY. Outputs могут приоритизировать research и тестировать гипотезы, но не давать execution permission.

### SX-23 — Event and protocol lifecycle strategy research

**Events:** token unlock/vesting; emissions and gauge schedules; ve-token/bribe/incentive epoch; listings and pool migrations; pool fee/tick/parameter changes; governance proposals/results; protocol upgrades/deployments; oracle changes; treasury/incentive announcements; market halt/resume.

**Acceptance:** event identity and source rights; announced-at vs effective-at vs observed-at timestamps; event finality/status; no look-ahead leakage; affected asset/protocol/market resolution; scenario replay before/after; market reaction and liquidity/cost evidence; event reversal/cancellation handling; causal controls. Signals не становятся executable quotes.

**Класс:** SIGNAL_ONLY / RESEARCH_ONLY; route generation только после независимого exact local market evidence.

### SX-24 — Chain admission and parallel dataset expansion

**Цель:** не расширять список сетей ради количества. Ранжировать candidate chains/data sources по реальной исследовательской полезности и совместимости с инфраструктурой.

**Initial candidate set for evidence-based review:** Solana; Sui; EVM Base/Arbitrum/Ethereum; Hyperliquid; TON; позже Starknet, Aptos и Cosmos только если официальные data interfaces и transaction semantics оправдают отдельный bounded lane.

**Per-chain scorecard:** canonical identity; official state/history interfaces; retention/gaps; source cost/quota/entitlement; finality/reorg; venue/lender/financing mechanisms; builder/simulation tooling; token representation; atomicity; security/licensing; replay availability; maintenance burden; overlap with existing source owners.

**Acceptance:** один source dossier на candidate; status ADMIT_READ_ONLY, WATCH_ONLY, BLOCKED или REJECT; воспроизводимый score breakdown; отсутствие endpoint/credential activation из документов; отсутствие второго AssetResolver, SourceRegistry, Dynamic Universe или quota ledger.

**Класс:** CONTROL_PLANE / RESEARCH_ONLY. Chain admission не равен strategy qualification.

### SX-25 — Opportunity half-life, competition and execution-latency intelligence

**Цель:** измерять, сохраняется ли opportunity после собственного data→decision→build→simulation pipeline. Моделировать time-to-expiry/decay, а не абстрактную “скорость бота”.

**Inputs:** source event time, observed/available time, quote request/response, provider latency, state generation, exact amount, build/simulation completion, candidate age, public transaction/competition observations where legally available, rejection/expiry/no-trade, landed/finalized outcome только когда реально доступно.

**Acceptance:** PIT-safe clocks; timestamp skew and missing data typed; opportunity decay curves per family/regime/venue/size; survival/competing-risk analysis; calibration/holdout; selection-bias and censored outcomes; public competition proxies are not called complete mempool or private orderflow; include provider/API/compute costs. Не использовать uncalibrated inclusion probabilities.

**Класс:** RESEARCH_ONLY / CONTROL_PLANE. Predictions могут менять приоритет verification, но не обходить exact quote, resource, build, simulation или paper gates.

## 3. Dataset expansion — один governed acquisition plane

Все новые datasets являются кандидатами, а не обещанными бесплатными/полными feeds. Для каждого фиксировать official API/schema/version, chain/market identity, source timestamp и available timestamp, history range, gap policy, rate/byte/query quotas, cost, retention, rights/licence, privacy, data quality, clock precision и PIT semantics.

| Dataset ID | Данные | Зачем нужны | Required treatment |
|---|---|---|---|
| DP-01 | Chain events, transactions, CPI/logs, account/object updates, checkpoints/blocks | Actual swaps, liquidations, pool changes, protocol events, state lineage | Finality/root, reorg/retraction, decoder revision, pagination, gap receipts |
| DP-02 | Direct DEX state: reserves, ticks, bins, orderbook L2, fee state | Exact route capacity and market impact | Pool/book identity, resource overlap, same-generation snapshot, exact input/output |
| DP-03 | CEX spot trades and public orderbook aggregates | CEX/DEX lead-lag, cross-venue benchmark | Licensed access, exchange sequence, depth level, timestamp semantics, no assumption of fill |
| DP-04 | Perpetual/futures funding, OI, basis, options IV/greeks, instrument specs | Derivative strategies and term structure | Contract multiplier, expiry, settlement, funding schedule, margin currency |
| DP-05 | Lending reserves, utilization, debt/collateral, borrow caps and liquidations | Lender-aware DEX and solvency strategies | Resource-specific rooted state; TVL/program existence is not borrowing capacity |
| DP-06 | Token/protocol lifecycle, vesting, unlocks, governance, emissions, listings and upgrades | Event-driven candidate generation | Event vs publication vs effect time, source rights, cancellation/correction |
| DP-07 | Public bot repositories and public transaction fingerprints | Strategy archetypes and execution pattern research | Licence audit; no deanonymization; no profitability claims from activity counts |
| DP-08 | First-party opportunity/quote/build/simulation/paper outcomes and latency | Own execution-quality and half-life model | Preserve reject, stale, failed, no-trade, reverted, simulated and finalized as distinct outcomes |

### Source candidates to assess — not automatically enable

- **Hyperliquid:** official WebSocket subscriptions include l2Book, trades, activeAssetCtx and user-specific fills/funding streams. Official historical-data guidance says archive updates are approximately monthly, may be missing or delayed, requester pays transfer costs, and S3 market history includes L2 snapshots rather than every desired series. Pair live capture with a measured completeness/retention contract; do not claim free complete history.
- **Deribit:** official public API documentation is a candidate source for options/futures instrument metadata, orderbook, OI and volatility data; exact methods, units, entitlements and current limits must be pinned before implementation.
- **Solana bot research:** the 2026 “Demystifying Solana Bots” study reports 586 GitHub repositories and 200 public chain addresses across more than 44 million transactions. A public Zenodo package exists, but its dataset licence must be resolved before ingestion or redistribution. Paper reuse permission is not the dataset licence.
- **Morpho / Sky:** protocol-native callback/auction mechanics are specific to source revisions and market deployments; pin exact official revision before adapter code.
- **SQD / Envio / exchange public archives / protocol subgraphs:** source candidates subject to current access, rate, completeness, licence and cost checks; “free tier” is not a production SLA or unlimited backfill.

Use existing QPR/DIN/SourceRegistry, DurableRawJournal, MarketObservation and dataset/replay owners. Do not create a second source catalog, ingestion scheduler, data lake or quota ledger.

## 4. Crosswalk: where each new family belongs

| New family | SX task | Existing owners to extend | Must not duplicate |
|---|---|---|---|
| DEX flash accounting | SX-17 | PR #638 quote/build kernel; existing financing/build/simulation/economic contracts; protocol-specific dossier | quote kernel, transaction compiler, signer/sender |
| Collateral-first callbacks | SX-18 | src/liquidation, src/lending_indexer, rights/evidence owners | lender registry, liquidation sender |
| Credit-conditioned AMM | SX-19 | FlashCapitalGraph, DEX exact evaluators, #638 pool dedup | capital graph, pool registry |
| Derivatives basis/options | SX-20 | existing market streams, source governance, decision dataset, economics | new global market DB, generic margin authority |
| Inventory OMS | SX-21 | existing orderbook/intent, AGG-05 conflict scheduler, inventory/capital owners | second orderbook/OMS store or scheduler |
| Bot archetypes | SX-22 | #541/#542, decision dataset, SourceRegistry, replay | second feature store or research ledger |
| Events/lifecycle | SX-23 | Dynamic Universe event lifecycle, EVO incentive/governance, source owners | second event bus or strategy registry |
| Chain/data admission | SX-24 | R09, QPR/DIN, Dynamic Universe, multichain owners | second chain registry, quota governance |
| Opportunity half-life | SX-25 | #541/#542, #500 AGG-10, R13-K, paper/decision dataset | new journal, quote plane or paper authority |

## 5. Parallel dependency plan

1. **Coordinator refresh:** latest main, open PRs, CI, owners and branch collisions. SX-00 is already complete in #639; refresh its output after #640 rather than rerunning the old baseline unchanged.
2. **Wave A — independent read-only research/dossiers:** SX-17…SX-24 source reviews, event/source schema proposals, datasets/licences and deterministic fixtures. Run in isolated worktrees after file ownership is frozen.
3. **Wave B — independent offline models:** protocol-native liabilities, collateral-first transitions, credit/DEX coupling, derivative models, inventory OMS, trader archetypes, event models and competition/half-life. Shared owners are serialized.
4. **Wave C — common contracts/integration:** map each candidate to canonical strategy contract SX-01, frozen quote/build seam #638, resource manifest and shared scheduler AGG-05/SX-12.
5. **Wave D — evidence/observability:** each family gets positive, negative, stale, partial, rejected and no-trade replay; include data/licence/cost/holdout status.
6. **SX-15/SX-16:** one coordinator reconciles both SX-01…SX-16 and SX-17…SX-25 into one versioned crosswalk/status proposal. Keep historical IDs; do not overwrite source archives or stale dashboard without exact-head refresh.

Recommended concurrency: 4–8 independent workers when the environment permits, each isolated to an approved path set. Set the actual number by file ownership, rate limits and agent capacity, not token allowance alone.

## 6. Definition of a ready strategy system

A family is DOCUMENTED only when its mechanism is described. It is IMPLEMENTED only when owner code, consumers and tests exist. It is EVIDENCE_QUALIFIED only when required real source/state/rights/quote/capacity/build/simulation/replay evidence passes for the exact deployment, asset, amount and generation. It is PAPER_QUALIFIED only after the paper acceptance protocol. LIVE_AUTHORIZED is outside this research pack.

Every family must have:
- stable ID and preserved prior IDs;
- falsifiable hypothesis, null, controls and counterexamples;
- canonical owner and exact changed paths;
- official source revision/deployment/ABI and licence/ToS decision;
- canonical asset/instrument/right identity;
- explicit execution class and transaction/holding horizon;
- exact amount/size-specific quote or instrument economics;
- lender/collateral/pool/book/resource manifest and no-double-use proof;
- full fees, funding, margin, rent, compute, data and failed-attempt costs;
- positive/negative/stale/partial/rejected/no-trade deterministic replay;
- time-blocked holdout, leakage controls, calibration and uncertainty where relevant;
- typed blockers and next dependency;
- rollback, test commands, CI evidence and PR link.

Unknown values remain null/UNKNOWN; no fabricated capacity, depth, causal relation, fill probability or profit.

## 7. Historical parallel-chat coverage and limitations

This reconciliation used:
- merged GitHub documents and PRs listed above;
- accessible saved conversation/archive extracts for Solana/Web3/flashloan strategy discussions;
- captured research handoffs and PR-358 market-relation research prompt;
- this conversation's strategy discussions, including learning from public trader/bot behavior.

The available archive is not a complete server-side transcript of every ChatGPT/parallel-agent conversation. Some archived pages explicitly have incomplete history or unverified capture continuity. Therefore this is a reconciled expansion of accessible evidence, **not a claim that every historical chat or every possible strategy has been exhaustively captured**. SX-24 and SX-25 include recurring research-discovery work so the catalog can continue to grow without silently duplicating owners or promoting unverified ideas.

## 8. Excluded or explicitly non-atomic

- Flash-loan governance attacks, vote manipulation and treasury abuse: excluded.
- Sandwich, frontrun, victim targeting, unauthorized/private order-flow access and third-party bot surveillance: excluded.
- Tokenized equities / Robinhood Stock Tokens: excluded by project policy.
- Bridges, CEX settlement/withdrawal, TON asynchronous multi-contract, cross-chain messages, delayed unstake/redemption, PT/YT maturity and multi-period carry: HEDGED_NON_ATOMIC / SIGNAL_ONLY unless a specific protocol proves a single valid settlement domain.
- An address's frequency, gross volume, route count, successful simulation or bot label is not proof of profitability.

## 9. Source references reviewed 2026-11-14

- Uniswap v4 Flash Accounting: https://developers.uniswap.org/docs/protocols/v4/concepts/flash-accounting
- Uniswap v4 Unlock Callback & Deltas: https://developers.uniswap.org/docs/protocols/v4/guides/unlock-callback-and-deltas
- Morpho pre-liquidation source: https://github.com/morpho-org/pre-liquidation
- Morpho Blue developer documentation: https://docs.morpho.org/developers/contracts/blue/
- Sky collateral liquidation: https://developers.skyeco.com/protocol/vaults/collateral-liquidation/
- Hyperliquid WebSocket subscriptions: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions
- Hyperliquid historical data: https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data
- Hyperliquid API rate limits: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits
- Deribit API documentation index: https://docs.deribit.com/
- “Demystifying Solana Bots: From GitHub Blueprints to On-Chain Fingerprints”: https://arxiv.org/abs/2607.28424
- Research dataset record (licence still to be reviewed): https://zenodo.org/records/21359451

These URLs are research references only. Before adding code or data, the assigned agent must fetch and pin exact official revision, deployment, licence, schema, units, limits and retrieval date.
