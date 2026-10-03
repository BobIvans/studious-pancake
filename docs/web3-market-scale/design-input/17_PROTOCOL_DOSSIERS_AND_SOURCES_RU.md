# Protocol dossiers и первичные источники

**Проверено чтение документации 3 октября 2026 UTC.** Дата чтения не является датой запуска. Ни onchain deployment, ни endpoint availability, ни profit здесь не измерены. PX — пакеты исследования, не новые подключённые providers.

## Изменения, которые нельзя пропустить

- DS-06/07: сентябрьские описания shared-liquidity composition содержат ограничения доступа и финансирования.
- DS-12/13: текущий filler guide расходится с остающимися legacy упоминаниями Priority.
- DS-04: наличие интеграционного руководства не доказывает наличие deployment на каждой сети.
- DS-25: опубликованный product/SDK не равен активному торгуемому рынку.
- DS-09: generic standard adapter требует implementation-specific проверки limits.

## Protocol dossier matrix

| ID | Пакет | Qualification status | Необходимое условие |
| --- | --- | --- | --- |
| PX-01 | Uniswap v4 hooks + accounting | DOC_ONLY | Один квалифицированный PoolKey/hook, известная fee function и закрытые deltas. |
| PX-02 | Fluid Lite | DOC_ONLY | Отдельная модель Lite и закреплённый deployment. |
| PX-03 | Fluid DEX v2 | BLOCKED_DEPLOYMENT_QUALIFICATION | Сначала deployment existence для выбранной сети. |
| PX-04 | Aqua / SwapVM / Aave composition | BLOCKED_ACCESS_AND_MODEL_QUALIFICATION | Проверенные taker rights плюс balance/allowance/health semantics. |
| PX-05 | Euler EVC | DOC_ONLY | Корректные account/controller/receiver identities и protocol health boundaries. |
| PX-06 | Morpho Vault V2 | DOC_ONLY | Product-specific max/cap handling, gate evidence, liquidity source. |
| PX-07 | Morpho Midnight | DOC_ONLY_NO_LIQUIDITY_PROOF | Exact maturity/collateral/gate identity и deployed implementation. |
| PX-08 | UniswapX Dutch RFQ | DOC_ONLY_WITH_DOCUMENTATION_DRIFT | Versioned reactor и eligibility at evaluation block. |
| PX-09 | CoW clearing | DOC_ONLY | Фиксированные пользовательские ограничения и fair comparator. |
| PX-10 | OIF / ERC-7683 / Across | DOC_ONLY_ASYNC_ONLY | Отдельный async lifecycle и inventory budget; pin proof/settler pair. |
| PX-11 | Flashblocks / ShredStream | DOC_ONLY_NO_ACCESS_OR_LATENCY_BENCHMARK | State reconstruction, commitments и invalidation до использования. |
| PX-12 | Sui DeepBook spot + margin | DOC_ONLY | Независимая Sui qualification; существующая Solana strategy остаётся disabled. |
| PX-13 | DeepBook Predict | BLOCKED_BY_DOCUMENTED_INACTIVE_MARKET_STATE | Проверить новые active markets и свежий oracle; до этого discovery-only. |
| PX-14 | HIP-3 markets | DOC_ONLY_NON_ATOMIC | Точные payoff/oracle/session/quote asset semantics и доступный hedge. |
| PX-15 | Boros + CrossEx reference | DOC_ONLY_NON_ATOMIC | Четыре согласованных cashflow exposures и inventory/margin до выхода. |
| PX-16 | x402 + verified evidence service | DOC_ONLY_NO_PAYMENTS | Явные service contract, verifier, rights и buyer demand. |

## PX-01 — Uniswap v4 hooks + accounting

Состояние: pool state, hook code/config, token behavior, unlock obligations.

Общие ресурсы: pool id, hook storage, settlement context.

Будущие проверки: hook upgrade invalidates cache; same hook affects two pools; all delta currencies close.

Первичные ссылки: DS-01, DS-02. Измеренная capacity/profit: UNKNOWN.

## PX-02 — Fluid Lite

Состояние: resolver block, pool reserves/model, fees/limits.

Общие ресурсы: pool id, singleton shared dependencies.

Будущие проверки: Lite != v2; complete state at one block.

Первичные ссылки: DS-03. Измеренная capacity/profit: UNKNOWN.

## PX-03 — Fluid DEX v2

Состояние: DEX type, debt/collateral shares, liquidity layer, hook/fees.

Общие ресурсы: underlying liquidity, credit capacity, hook state.

Будущие проверки: Ethereum TBD not admitted; shares are not raw asset atoms.

Первичные ссылки: DS-04. Измеренная capacity/profit: UNKNOWN.

## PX-04 — Aqua / SwapVM / Aave composition

Состояние: maker real balance, virtual allocation, strategy hash, allowance, credit health.

Общие ресурсы: maker/token, app/strategy, collateral account.

Будущие проверки: no double count across strategies; revoked allowance invalidates all routes; prefix health.

Первичные ссылки: DS-05, DS-06, DS-07. Измеренная capacity/profit: UNKNOWN.

## PX-05 — Euler EVC

Состояние: account state, vault caps, controller, oracle, checks deferred scope.

Общие ресурсы: account debt, collateral pool, vault cash.

Будущие проверки: simulation-mode divergence; receiver vs account mismatch.

Первичные ссылки: DS-08. Измеренная capacity/profit: UNKNOWN.

## PX-06 — Morpho Vault V2

Состояние: vault shares, adapter allocation, caps/gates, withdrawable assets, index block.

Общие ресурсы: underlying market, adapter capacity, idle assets.

Будущие проверки: zero max does not infer universal economic zero; unlisted discovery coverage.

Первичные ссылки: DS-09, DS-10. Измеренная capacity/profit: UNKNOWN.

## PX-07 — Morpho Midnight

Состояние: market id, maturity, loan token, collateral/oracle, gate state.

Общие ресурсы: debt by market, collateral, loan inventory.

Будущие проверки: future credit not spendable cash; flash closure separate from maturity.

Первичные ссылки: DS-11. Измеренная capacity/profit: UNKNOWN.

## PX-08 — UniswapX Dutch RFQ

Состояние: order bytes, reactor, nonce/cancel, exclusivity, block decay, available_at.

Общие ресурсы: order fillability, maker balance, routing pools.

Будущие проверки: exclusive order reject; bounded feed coverage; unknown order variant quarantine.

Первичные ссылки: DS-12, DS-13, DS-14. Измеренная capacity/profit: UNKNOWN.

## PX-09 — CoW clearing

Состояние: batch orders, limits, fee rules, partial fill, common pool state.

Общие ресурсы: user balances, orders, pools.

Будущие проверки: per-user no worse; do not equate procurement auction with swap clearing.

Первичные ссылки: DS-15. Измеренная capacity/profit: UNKNOWN.

## PX-10 — OIF / ERC-7683 / Across

Состояние: origin escrow/lock, destination fill, proof status, refund deadline, settlement chain.

Общие ресурсы: inventory per domain, repayment claims, shared proof provider.

Будущие проверки: fill != settled; out of order proof; timeout traps inventory.

Первичные ссылки: DS-16, DS-17, DS-18, DS-19, DS-30, DS-31. Измеренная capacity/profit: UNKNOWN.

## PX-11 — Flashblocks / ShredStream

Состояние: event sequence, provisional generation, parent block, received_at, commitment.

Общие ресурсы: upstream provider, network quota, reorg scope.

Будущие проверки: provisional correction; gap triggers backfill; no timestamp-only cross-domain join.

Первичные ссылки: DS-20, DS-21, DS-22. Измеренная capacity/profit: UNKNOWN.

## PX-12 — Sui DeepBook spot + margin

Состояние: object version, package revision, book depth, fees, balance manager, margin pool.

Общие ресурсы: shared object, balance manager, margin cash.

Будущие проверки: lot residual; shared balance across pools; isolated margin.

Первичные ссылки: DS-23, DS-24. Измеренная capacity/profit: UNKNOWN.

## PX-13 — DeepBook Predict

Состояние: condition/expiry, oracle update, settlement state, quote coin type, package revision.

Общие ресурсы: outcome collateral, pool vault.

Будущие проверки: expired unsettled market rejects candidate.

Первичные ссылки: DS-25. Измеренная capacity/profit: UNKNOWN.

## PX-14 — HIP-3 markets

Состояние: DEX identity, asset id, oracle/index, margin terms, halt state.

Общие ресурсы: per-DEX collateral, hedge capacity, oracle lineage.

Будущие проверки: ticker collision; halted hedge; independent margin.

Первичные ссылки: DS-26. Измеренная capacity/profit: UNKNOWN.

## PX-15 — Boros + CrossEx reference

Состояние: YU units, underlying index, maturity, perp positions, settlement interval, fees.

Общие ресурсы: margin per venue, borrow, custody, funding index.

Будущие проверки: one-leg failure; funding index mismatch; hedge close cost.

Первичные ссылки: DS-27, DS-28. Измеренная capacity/profit: UNKNOWN.

## PX-16 — x402 + verified evidence service

Состояние: task hash, source license, state hash, quote/fee, result receipt.

Общие ресурсы: provider quota, common upstream, verification budget.

Будущие проверки: paid but wrong answer; duplicate receipt; verification costs exceed benefit.

Первичные ссылки: DS-29. Измеренная capacity/profit: UNKNOWN.

## Реестр первичных свидетельств

Факты ниже — пересказ конкретного источника. Модели, связки CB и приоритеты — наши исследовательские предложения. Mutable URLs ещё нужно закрепить по версии при разработке.

### DS-01 — Uniswap v4 hooks

[Первичный источник](https://developers.uniswap.org/docs/protocols/v4/concepts/hooks)

Hooks расширяют операции пула; hook identity является частью конкретной конфигурации.

Нужна квалификация каждого hook implementation и изменяемых параметров.

Дата публикации/изменения, если видна: не установлена.

### DS-02 — Uniswap v4 flash accounting

[Первичный источник](https://developers.uniswap.org/docs/protocols/v4/concepts/flash-accounting)

Внутренние deltas позволяют отложить передачи токенов; в конце unlock context обязательства должны закрыться.

Отложенный внутренний расчёт не создаёт внешнюю кредитную линию и не отменяет gas.

Дата публикации/изменения, если видна: не установлена.

### DS-03 — Fluid DEX Lite integration

[Первичный источник](https://docs.fluid.instadapp.io/integrate/dex-lite-swaps.html)

Документирован singleton DEX для correlated pairs и resolver для discovery/state.

Заявления о gas не заменяют измерение выбранного маршрута; deployment и state не проверены.

Дата публикации/изменения, если видна: не установлена.

### DS-04 — Fluid DEX v2 integration

[Первичный источник](https://docs.fluid.instadapp.io/integrate/dex-v2-swaps.html)

Документированы несколько AMM-моделей, smart collateral/debt, hooks и flash accounting; Ethereum addresses указаны TBD, Polygon перечислен.

Это состояние таблицы документации, не независимая onchain-проверка доступности.

Дата публикации/изменения, если видна: не установлена.

### DS-05 — Aqua reference implementation

[Первичный источник](https://github.com/1inch/aqua)

Registry хранит virtual balances maker/app/strategy/token; реальные активы находятся в wallet.

README не доказывает доступную совокупную ликвидность или соответствие конкретному deployed code.

Дата публикации/изменения, если видна: не установлена.

### DS-06 — Aqua with Aave loops

[Первичный источник](https://1inch.com/blog/post/aqua-use-cases-looped-multi-positions)

Описана композиция aToken-позиций с Aqua и порядком incoming/outgoing collateral.

Borrow cost, health constraints и зависимость fee income от потока сохраняются.

Дата публикации/изменения, если видна: 2026-09-15.

### DS-07 — Aqua taker access

[Первичный источник](https://1inch.com/blog/post/whos-filling-1inch-aqua-orders)

На описанном этапе takers через routing infrastructure — verified resolvers с onchain credential.

Permissionless maker side не означает открытый доступ любого taker.

Дата публикации/изменения, если видна: 2026-09-14.

### DS-08 — Euler EVC integration

[Первичный источник](https://docs.euler.finance/build/evc/integration-guide/)

EVC поддерживает atomic batch, subaccounts и simulation; called contracts могут распознавать simulation mode.

Не переносить права account/controller автоматически и не считать simulation доказательством исполнения.

Дата публикации/изменения, если видна: не установлена.

### DS-09 — Morpho Vaults V2 contract semantics

[Первичный источник](https://docs.morpho.org/developers/contracts/morpho-vaults-v2/)

maxDeposit/maxMint/maxWithdraw/maxRedeem всегда возвращают ноль; пределы рассчитываются по специализированным правилам.

Общий ERC-4626 adapter должен fail closed до product-specific qualification, а не угадывать capacity.

Дата публикации/изменения, если видна: не установлена.

### DS-10 — Morpho vault data API

[Первичный источник](https://docs.morpho.org/developers/api/morpho-vaults/)

Public REST даёт listed vault directories; unlisted discovery и часть метрик доступны через GraphQL.

Listed directory не полный universe; rate limits, индексированный block и права данных проверяются отдельно.

Дата публикации/изменения, если видна: не установлена.

### DS-11 — Morpho Midnight

[Первичный источник](https://docs.morpho.org/developers/contracts/midnight/)

Fixed-rate markets включают maturity, collateral/oracle parameters, gates и callback/flashLoan interfaces.

Наличие спецификации не доказывает ликвидный deployment; maturity cashflows не instant flashloan return.

Дата публикации/изменения, если видна: не установлена.

### DS-12 — UniswapX fillers overview

[Первичный источник](https://developers.uniswap.org/docs/liquidity/uniswapx/filling/overview)

Актуальное руководство направляет в RFQ/exclusive Dutch; quoter permissioned, non-exclusive filler имеет отдельные условия доступа.

Orders endpoint cached, latest 50, документирован предел 4 RPS; это не полный исторический order stream.

Дата публикации/изменения, если видна: не установлена.

### DS-13 — UniswapX Priority guide deprecation

[Первичный источник](https://developers.uniswap.org/docs/liquidity/uniswapx/filling/priority-chain/filling-on-op-stack)

Priority-auction guide помечен deprecated и направляет новые интеграции к Dutch V3.

Другие glossary/deployment pages ещё упоминают Priority; точную версию reactor/response следует pin, changelog не удалось открыть.

Дата публикации/изменения, если видна: не установлена.

### DS-14 — UniswapX Dutch V3

[Первичный источник](https://developers.uniswap.org/docs/liquidity/uniswapx/filling/dutch-v3-chains/filling-on-dutch-v3-chains)

Exclusivity и decay измеряются block numbers; soft override возможен при конкретных условиях order.

Один секундный clock для всех auction variants неверен; eligible order проверяется отдельно.

Дата публикации/изменения, если видна: не установлена.

### DS-15 — CoW fair combinatorial auction

[Первичный источник](https://docs.cow.fi/cow-protocol/concepts/introduction/fair-combinatorial-auction)

Batch bids сравниваются с индивидуальными предложениями и фильтруются по пользовательскому результату.

Максимум solver profit не заменяет per-user ограничения clearing.

Дата публикации/изменения, если видна: не установлена.

### DS-16 — Open Intents Framework

[Первичный источник](https://docs.openintents.xyz/docs)

OIF разделяет InputSettler, OutputSettler и oracle/proof layer; поддерживает разные collection flows.

Общий интерфейс не уравнивает trust, timing и settlement assumptions разных deployments.

Дата публикации/изменения, если видна: не установлена.

### DS-17 — OIF solver implementation

[Первичный источник](https://github.com/openintentsframework/oif-solver)

Публичный solver содержит discovery, pricing и settlement компоненты; README предупреждает об alpha.

Reference only: не запускать quickstart и не импортировать signer/execution subsystem в shadow engine.

Дата публикации/изменения, если видна: не установлена.

### DS-18 — Across V4 settlement

[Первичный источник](https://docs.across.to/guides/concepts/across-v4)

V4 добавляет SP1-based проверку сообщений settlement; optimistic bundle stage остаётся в описанной архитектуре.

ZK-слой не делает быстрый fill одновременным с reimbursement и не устраняет все предположения доверия.

Дата публикации/изменения, если видна: не установлена.

### DS-19 — Across intent lifecycle

[Первичный источник](https://docs.across.to/guides/concepts/intent-lifecycle)

Initiation, destination fill за капитал relayer и последующее settlement — разные этапы; бывает exclusivity.

Время пользовательского fill нельзя подставить как период оборота капитала relayer.

Дата публикации/изменения, если видна: не установлена.

### DS-20 — Base RPC and Flashblocks

[Первичный источник](https://docs.base.org/base-chain/api-reference/rpc-overview)

pending представляет preconfirmed Flashblock; public endpoints HTTP-only, WSS требует подходящего провайдера.

Preconfirmation не finalized state; публичный HTTP не даёт бесплатную WSS подписку.

Дата публикации/изменения, если видна: не установлена.

### DS-21 — Unichain overview

[Первичный источник](https://developers.uniswap.org/docs/unichain)

Документированы Flashblocks preconfirmations как слой быстрого feedback поверх block production.

Возможность читать раньше не гарантирует first fill или прибыль; это отдельный latency benchmark.

Дата публикации/изменения, если видна: не установлена.

### DS-22 — Jito ShredStream

[Первичный источник](https://docs.jito.wtf/lowlatencytxnfeed/)

Proxy получает shreds; setup требует approved public key и инфраструктуру приёма.

Тариф и доступ пользователя не подтверждены; шреды требуют реконструкции state, никакой auth setup здесь не выполнен.

Дата публикации/изменения, если видна: не установлена.

### DS-23 — Sui DeepBook V3 design

[Первичный источник](https://docs.sui.io/onchain-finance/deepbook/deepbookv3/design)

Pool и BalanceManager — отдельные shared objects; один BalanceManager может обслуживать несколько pools.

Отдельные books не означают независимые balances; SDK не квалифицирует подписки.

Дата публикации/изменения, если видна: не установлена.

### DS-24 — Sui DeepBook Margin

[Первичный источник](https://docs.sui.io/onchain-finance/deepbook/deepbook-margin/)

MarginManager использует один margin pool за раз; модель isolated, с liquidation constraints.

Не переносить cross-margin assumptions иных venues.

Дата публикации/изменения, если видна: не установлена.

### DS-25 — Sui DeepBook Predict

[Первичный источник](https://docs.sui.io/onchain-finance/deepbook/deepbook-predict/)

Страница сообщает о deployment 12 сентября 2026, но на последнем записанном chain read рынки истекли без settlement и quote/mint abort.

Не объявлять торгуемым: дата последнего chain read не установлена нами, live RPC проверки не было.

Дата публикации/изменения, если видна: 2026-09-12 (deployment date reported by docs).

### DS-26 — Hyperliquid HIP-3

[Первичный источник](https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-3-builder-deployed-perpetuals)

Builder определяет oracle/contract settings; perp DEX instances имеют собственные margining и books.

Совпадение тикера не гарантирует одинаковый claim, oracle, market session или общий collateral.

Дата публикации/изменения, если видна: не установлена.

### DS-27 — Boros funding settlement

[Первичный источник](https://docs.pendle.finance/boros-docs/about-boros/funding-rate-settlement)

Fixed/floating cashflows рассчитываются периодически до maturity и меняют collateral.

Позиция требует margin на всём горизонте; quoted APR не realised profit.

Дата публикации/изменения, если видна: не установлена.

### DS-28 — Pendle CrossEx research tool

[Первичный источник](https://docs.pendle.finance/boros-docs/arbitrage-with-crossex/overview)

Pendle описывает experimental open-source dashboard для четырёх legs Boros и CrossEx perp hedges.

Приложение ставит реальные orders; здесь только design reference. Hedge mismatch, fees и partial fills требуют собственной проверки.

Дата публикации/изменения, если видна: не установлена.

### DS-29 — x402 introduction

[Первичный источник](https://docs.x402.org/introduction)

HTTP payment standard позволяет продавать API/content и автоматизировать оплату запросов.

Payment receipt не доказывает правильность данных/solver result; бесплатный стандарт не означает бесплатную услугу.

Дата публикации/изменения, если видна: не установлена.

### DS-30 — ERC-7683

[Первичный источник](https://eips.ethereum.org/EIPS/eip-7683)

Общий формат разрешения intent и его требований служит интерфейсом между системами.

Pin version: не предполагать один escrow, resolver, proof или атомарный settlement для всех implementations.

Дата публикации/изменения, если видна: не установлена.

### DS-31 — Across API access

[Первичный источник](https://docs.across.to/introduction)

Текущее introduction требует API key для production use Swap API.

Не считать production API автоматически доступным без ключа или бесплатным без тарифной проверки.

Дата публикации/изменения, если видна: не установлена.

## Данные и стоимость доступа

| Пакет | Что можно исследовать | Что не предполагать |
| --- | --- | --- |
| Morpho | Public REST/GraphQL discovery, allocations and state metadata (DS-10) | Directory completeness, archival point-in-time truth or unlimited quota |
| UniswapX | Bounded current order reads (DS-12) | Full order history, every RFQ opportunity or verified subscription |
| Fluid/Euler/AMMs | Contract resolvers and documented models | Free unlimited RPC, exact state from dashboard price |
| Aqua | Public code and protocol descriptions | Open taker rights through every routing path |
| OIF/Across | Open framework/reference implementations and lifecycle (DS-16..19/31) | Free production API, deployable solver without operating capital |
| Base/Unichain/Jito | Faster state-delivery design references | Same commitment as final state, user access or cost-free low latency |
| Sui/Hyperliquid | Versioned object/book and instrument descriptions | Permission to enable existing OrderbookAmmStrategy |
| x402/CrossEx | Service/hedge design references | Free paid services, customer demand or safe autorun |

Исходный каталог 43 источников и 7 watchlist-кандидатов сохранён. Эти 16 dossiers не прибавляются к нему как якобы 16 работающих feeds. Общая цена включает data rights, requests, RPC, egress, storage, decoding, retries, CPU и verification. Новые API probes в этом обновлении не выполнялись.

Не использованы как evidence: нерелевантные результаты поисков, неоткрывшийся UniswapX changelog и старые Flashblocks URL. Discovery не равен admission.
