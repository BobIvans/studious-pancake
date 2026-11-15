# ИТОГОВЫЙ ОТЧЁТ — R10-1: pre-API market → route → paper qualification closure

**Дата:** 2026-11-15
**Ветка:** `codex/pre-api-market-route-qualification-2026-11-15`
**База:** origin/main `731915149365d7b31f5f93deb1b08e894372b0f8` (PR #658 — контракт задания, слит как docs-only в 01:29 UTC; реализация идёт отдельным PR с этой ветки)
**Задание:** `CODEX_START_HERE_RU.md` + `CODEX_TRIGGER_RU.txt` (прочитаны полностью), PR #658.

## 1. Что сделано

Закрыт интеграционный вертикал R10-1 (был `PLANNED` в MASTER00): существующий two-leg
детектор → граф-топология → точная CPMM-оценка → R13-K дедуп пулов → PR118
немонотонный сайзинг → all-in экономика → fail-closed paper seam. Новых стратегий,
графов, солверов, quote-kernel'ов, журналов, capital-графов, шедулеров или
authority gates НЕ добавлено.

### Изменённые файлы

| Файл | Тип | Что внутри |
|---|---|---|
| `src/strategy/cpmm_cycle_binding.py` | NEW | Канонический владелец R10-1: `CpmmBindingRejection` (типированные причины, вкл. `NO_QUALIFIED_LENDER_EDGE` / `BUILDER_UNQUALIFIED` / `SIMULATION_SOURCE_BLOCKED` / `QPR_NOT_READY`), `VenueKind`, `RouteSupport`, `PoolLineage`, `BlockedVenueCandidate`, `PaperGateInputs`+`evaluate_paper_gate`, `evaluate_exact_two_leg_route` (последовательное распространение conservative output, без масштабирования котировок), `classify_route_support`, R13-K `PoolIdentityDeduplicator` на уровне пулов и попарно на уровне маршрута, AGG-05 shortlist с exact-промоушеном только для CPMM 2/3/4-hop, PR118 свежая точная переоценка на каждый размер, `run_pre_api_route_qualification_replay` → отчёт с метриками стадий, раздельными ratio, provenance `fixture-replay`, детерминированным sha256-дайджестом; sign/send/live жёстко False |
| `src/strategy/exact_cpmm_capacity.py` | EDIT (аддитивно) | `CapacityEconomics.ledger_for_legs(...)` — обобщение all-in PR118-леджера на 2-leg последовательности; `ledger_for` делегирует в него. Существующее поведение не изменено |
| `tests/test_sxr1_cpmm_cycle_binding.py` | NEW | 25 unit-тестов (см. §3) |
| `scripts/r10_1_pre_api_route_replay.py` | NEW | Детерминированный офлайн-реплей 7 сценариев + дайджест |
| `docs/roadmap/pre-api-market-route-qualification-2026-11-15/replay_report_2026-11-15.json` | NEW | Артефакт реплея (7 сценариев, fixture/replay) |
| `docs/roadmap/STUDIOUS_PANCAKE_MASTER_CODEX_EXECUTION_2026-11-13/MASTER00_IMPLEMENTATION_MATRIX.json` | EDIT | R10-1: `PLANNED` → `IMPLEMENTED_UNQUALIFIED`, PR/evidence/blockers |
| `docs/roadmap/agent-execution-master-2026-11-13/PARALLEL_EXECUTION_STATUS.json` | EDIT | current_main `73191514`, запись R10-1 |
| `config/format_targets.txt` | EDIT | +4 пути (CI black-check) |

### Переиспользованные канонические владельцы (дублей нет)

`CircularArbitrageDetector`/`DetectorPair` (two-leg, PR-033/113), `enumerate_exact_cpmm_routes`/`evaluate_exact_cpmm_route`/`QualifiedCpmmState` (PR559), `search_bounded_cycles` (AGG-05, топология 2–5 hop), `PoolIdentityDeduplicator` (R13-K, #638), `build_pr118_amount_grid`/`evaluate_pr118_non_monotonic_sizing`/`PR118TypedCostLedger` (PR118), `DurableCapitalCoordinator` (PR-057), `BuildStatus`-семантика R03 (contract), `ObservationBatch`/`MarketObservationV2` (MPR-042). Preflight: открытые PR #649/#655/#657 и worktree `sp-worktrees/r10-cpmm-binding` (стоит на базе `a82a512b`, коммитов нет) — пересечений нет.

## 2. Матрица поддержанных маршрутов

| Форма | Venue | Hop | Статус |
|---|---|---|---|
| A→B→A | Raydium CPMM | 2 | **EXACT_SUPPORTED** (two-leg детектор + точная оценка + PR118) |
| Треугольник | Raydium CPMM | 3 | **EXACT_SUPPORTED** |
| Цикл | Raydium CPMM | 4 | **EXACT_SUPPORTED** |
| Любая | Raydium CPMM | 5 | **SHORTLIST_ONLY** (топология, никогда exact-промоушен) |
| Любая | Raydium CLMM | — | **BLOCKED** (`MISSING_VENUE_STATE`: tick-array/bitmap) |
| Любая | Meteora DLMM | — | **BLOCKED** (`MISSING_VENUE_STATE`: bin arrays) |
| Любая | Orderbook/CLOB | — | **BLOCKED** (`UNSUPPORTED_VENUE_KIND`) |

Marginal-rate shortlist — только топология; exact-промоушен только если каждый leg
имеет amount-специфичный точный эвалюатор на одной valid generation.

## 3. Тесты и команды (точные)

```
.venv/Scripts/python.exe -m pytest tests/test_sxr1_cpmm_cycle_binding.py tests/test_exact_cpmm_capacity.py tests/test_pr118_non_monotonic_sizing.py tests/test_r13_kernel_contract.py tests/test_shadow_arbitrage_graph.py tests/test_agg05_multihop_solver.py tests/test_pr033_snapshot_detectors.py -q
→ 149 passed (из них 25 новых)
.venv/Scripts/python.exe -m mypy src/strategy/cpmm_cycle_binding.py src/strategy/exact_cpmm_capacity.py --config-file mypy.ini → Success: no issues
.venv/Scripts/python.exe -m black --check <изменённые файлы> → clean
.venv/Scripts/python.exe -m flake8 <изменённые файлы> → clean
.venv/Scripts/python.exe -I scripts/r10_1_pre_api_route_replay.py --output docs/roadmap/pre-api-market-route-qualification-2026-11-15/replay_report_2026-11-15.json
→ 7 сценариев, детерминизм подтверждён (совпадение дайджестов повторного прогона)
```

Позитив: two-leg; 3-pool треугольник (немонотонный оптимум: gross 6/9/8 на 10/20/30,
при fee 7 выбран 20); 4-pool цикл; последовательное распространение сумм.
Негатив: gross>0 но net<0; marginal-shortlist отвергнут точным эвалюатором;
unknown-стоимость в неденоминации блокирует (не ноль); stale; mixed generation;
slot skew; wrong program/decimals; не замкнутый путь; повтор venue; алиас одного
пула через агрегаторы; unknown lineage; CLMM/DLMM/orderbook; 5-hop; все стадии
paper gate; детерминизм; отсутствие signer/sender/live; отсутствие единого
«success rate» (5 раздельных ratio).

## 4. Результаты реплея (fixture/replay, НЕ живые данные)

| Сценарий | topology | exact_qualified | net_positive | paper_complete |
|---|---|---|---|---|
| two-leg-positive | 1 | 1 | 1 | 0 (`NO_QUALIFIED_LENDER_EDGE`) |
| 3-pool triangle | 2 | 2 | 1 | 0 |
| 4-pool cycle | 2 | 2 | 1 | 0 |
| pool-alias | 0 | 0 | 0 | 0 (обе alias-копии отвергнуты) |
| unknown-lineage | 0 | 0 | 0 | 0 (UNKNOWN ≠ independent) |
| blocked-venue | 0 | 0 | 0 | 0 (типированные блокировки) |
| determinism-proof | 2 | 2 | 1 | 0 |

`paper_complete_count = 0` всегда — честное состояние main: 0 квалифицированных
lender edges, билдеры `BUILT_OFFLINE_UNQUALIFIED`, симуляция заблокирована, QPR
не готов. Кандидаты сохраняются с точной причиной блокировки.

## 5. Оставшиеся блокеры R02–R06 (не закрываются этим PR)

- **R02** — 0 квалифицированных capital edges; нужна живая корневая RPC-квота (`LIVE_ROOTED_RPC`) / операторские данные.
- **R03** — билдеры без conformance (`OPERATOR_ACCOUNT_INPUT_REQUIRED`, ABI-пины); `BUILT_OFFLINE_UNQUALIFIED` ≠ готовность.
- **R04** — BLOCKED: требует R02+R03.
- **R05** — BLOCKED: требует R04-кандидата + governed RPC (сейчас `_BlockedRpcClient`).
- **R06** — BLOCKED: требует R05 evidence + QPR readiness.

## 6. Preflight следующего (отдельного) read-only API-capture PR — только подготовка

1. DEX Screener discovery → точная каноническая identity; индексированная ликвидность ≠ исполняемая глубина.
2. Raydium API V3 metadata/config; Meteora Data API — как доп. discovery; затем on-chain state read.
3. Jupiter V2 `/swap/v2/order` — quote-only, без taker, одинаковые raw-размеры и ограниченный time skew.
4. 0x Solana `/solana/swap-instructions` — после проверки API key/taker/schema/headers; инструкции — инертное evidence. Требование `0x-version` сверить с контрактом Solana-эндпоинта — не угадывать.
5. Независимые Solana RPC источники; pool/vault/mint/tick/bin в общем `getMultipleAccounts` контексте; слот/provenance/квота.
6. Точный эвалюатор Raydium CPMM — первым; CLMM/DLMM — только после полного паритета state/math/fee.

Перед кампанией перепиновать доки: solana.com/docs/rpc/http/getmultipleaccounts, developers.jup.ag/docs/swap (+/order), docs.0x.org/solana/..., docs.dexscreener.com/api/reference, api-v3.raydium.io/docs, docs.meteora.ag/...dlmm/sdk. Проверить квоты, авторизацию, версии, OpenAPI-схемы, лицензии, retention. Никогда не коммитить/печатать креденшелы.

## 7. Безопасность / hard stop

В этом PR нет и не появилось: секретов, кошельков, создания аккаунтов/ATA, подписи,
отправки, заимствований, трат, деплоя, активации провайдеров, live mode, production
promotion. `sign_enabled=send_enabled=live_mode=False` в отчёте; существующие
fail-closed гейты не тронуты. Все входы/выходы помечены `fixture-replay`;
`contains_live_evidence=false`. Смешивание fixture и live счётчиков исключено.

**Успешный fixture-реплей означает готовность субстрата к отдельному контролируемому
read-only API-capture PR — это НЕ доказательство рыночной прибыльности, реального
исполнения или live-готовности.**
