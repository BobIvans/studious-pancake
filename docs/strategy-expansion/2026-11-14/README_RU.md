# Strategy Expansion Pack — 2026-11-14

Это отдельный additive strategy-knowledge и execution-planning слой для studious-pancake. Он НЕ заменяет, не копирует и не переписывает `MASTER FLASHLOAN MARKET INTEGRATION — CODEX ASSIGNMENT`, P0 market-intake/quote work, текущий R10 inventory или уже работающие параллельные агентские ветки.

## Цель

Свести ранее исследованные стратегии в один проверяемый каталог, выявить пробелы относительно существующих Strategy Atlas / OP-01…OP-28 / WG-01…WG-28 / R10 A…I, и дать агентам независимые, но согласованные work packages. Результат — не обещание доходности и не автоматическое включение стратегий, а технически полная система знаний, адаптерных требований, экономических моделей, replay и критериев допуска.

## Проверенные источники в main на момент подготовки

- `docs/web3-market-scale/design-input/04_STRATEGIES_RU.md` — S01–S07 и Market-of-Markets.
- `docs/web3-market-scale/design-input/25_OPPORTUNITY_ATLAS_RU.md` — OP-01…OP-28.
- `docs/web3-market-scale/design-input/data/tasks.json` — WG-01…WG-28.
- `docs/roadmap/STUDIOUS_PANCAKE_MASTER_CODEX_EXECUTION_2026-11-13/STRATEGY_UNIVERSE_ATLAS.md`.
- `docs/roadmap/STUDIOUS_PANCAKE_MASTER_CODEX_EXECUTION_2026-11-13/STRATEGY_CROSSWALK.json`.
- `docs/roadmap/STUDIOUS_PANCAKE_MASTER_CODEX_EXECUTION_2026-11-13/ARCHIVE_RESEARCH_CROSSWALK.md`.
- `docs/roadmap/agent-execution-master-2026-11-13/tasks/R10_STRATEGIES_AND_INTELLIGENCE.md`.
- `docs/roadmap/agent-execution-master-2026-11-13/tasks/R10_STRATEGY_INVENTORY_2026-11-14.md`.
- `docs/roadmap/agent-execution-master-2026-11-13/reports/R10_STRATEGY_REPLAY_EXPERIMENTS_2026-11-14.md`.

R10 inventory/replay explicitly states that it made no `src/` strategy-owner changes; the current supported entrypoint has six registrations: circular arbitrage, LST depeg, LST unstake, Kamino liquidation, Pump migration and orderbook/AMM. Only circular arbitrage is a real shadow detector path (two-leg); Pump is boundary-only; LST are stubs; liquidation and orderbook are fixture-only/quarantined. Do not confuse this registry count with the much larger research universe.

## Pack contents

- `STRATEGY_GAP_ANALYSIS_RU.md` — what is already covered and the genuinely missing strategy mechanisms.
- `STRATEGY_CATALOG_AND_EXECUTION_CLASSES_RU.md` — canonical taxonomy, atomicity classes, economics and strategy contract.
- `PARALLEL_STRATEGY_EXECUTION_ARCHITECTURE_RU.md` — shared-state, resource reservation, portfolio scheduling and parallelism.
- `STRATEGY_EXPANSION_ASSIGNMENTS_RU.md` — coordinated implementation/research work packages and dependencies.
- `STRATEGY_ACCEPTANCE_MATRIX.json` — machine-readable strategy families, proof gates and status vocabulary.
- `CODEX_STRATEGY_EXPANSION_START_HERE.md` — legacy SX-only pointer; the authoritative campaign trigger is `CODEX_STRATEGY_CAMPAIGN_START_HERE.md`.
- `ARCHIVE_DETECTOR_TAXONOMY_COVERAGE_GATE_RU.md` + `ARCHIVE_DETECTOR_TAXONOMY_CROSSWALK_V1.json` — SX-17 reconciliation of V3's 64 anomaly classes, V4's 25 detectors, 19 V3 routes, 36 V6 routes, 12 V6 hyperedges and 4 funding primitive references.
- `PAIR_ARCHIVE_COVERAGE_AND_IMPORT_GATE_RU.md` + `02_ALL_NEW_CURRENCY_PAIRS_V6_SOURCE_2026-10-08.md` — pair-by-pair proof requirements and the preserved V6 catalog.

## Binding non-goals

- No live signing, wallet creation, borrow, transaction submission, Jito sender, production promotion or env-flag bypass.
- No assumption that symbol pairs, TVL, aggregator route labels, oracle prices, bridge flows or historical correlations are executable markets.
- No cross-chain bridge/CEX/perpetual holding period represented as one atomic flashloan route.
- No Robinhood Stock Tokens or tokenized equities.
- No copied third-party SDK/code without license and revision review.
- No duplicate graph, solver, asset registry, market database, correlation ledger, journal, capital graph, admission authority or execution pipeline. Extend canonical owners.
- PRs must remain reviewable, tested and evidence-backed. For this defined strategy / Build Bigger Universe / flashloan campaign, the repository owner explicitly delegated in-scope PR creation, review and merge authority on 2026-11-14. The agent may merge only after current required checks, provenance/license review, owner-overlap audit, resolved review threads, clean rebase, mergeability and branch protection all pass. This is not permission for on-chain or financial actions.

## How to use

Place this directory in the repository as-is. Agents should start from `CODEX_STRATEGY_EXPANSION_START_HERE.md`, read the source files above, refresh all statuses against current main and active PRs, then execute independent work packages in parallel only where ownership/dependencies permit. The pack must remain an additive overlay: the active market-integration assignment is owned by its existing agents.



## Актуализация стратегии и runtime — 2026-11-14

Проверенная основная ветка на момент этого handoff: \`9f173d7632cb30190bb8d9174ceba6d116eaec70\`.

С момента предыдущей матрицы объединены:
- #645 SX-12 — deterministic offline portfolio optimizer над SX-01 ResourceManifest + AGG-05;
- #646 — полный MASTER FLASHLOAN + Build Bigger Universe archive recovery;
- #647 — Titan adapter на frozen R13-K kernel, offline/sender-free;
- #648 SX-08 — exact Fraction rate/refinance research model;
- #650 — точный архивный dataset исторических pair/relationship rows, hash-pinned;
- #651 SX-07 — conditional outcome vector / complete-set conservation research model;
- #653 SX-02 — flash-mint vs lender economics research model;
- #654 SX-17 — V3/V4/V6 archive detector/anomaly taxonomy, archive-only.

Новые work packages:
- **SX-18** — runtime multi-strategy fanout: провести доказуемую границу между каталогом стратегий и реальным installed runtime. Сейчас шесть registrations, но только circular_arbitrage имеет реальный two-leg shadow detector. Использовать существующие owners, не создавать второй registry/queue/scheduler.
- **W6-12** — public/authorized pseudonymous on-chain participant strategy intelligence: полные эпизоды, net attribution, failed/censored events, replay и holdout. Без deanonymization, doxxing, private flow или auto-copy-trading.

Открытые workstreams в текущем snapshot: #649 SX-03 LLAMMA (proprietary source / primary evidence blockers), #655 R10-2 MarginFi offline bridge (rebase/review требуется) и #657 SX-18/W6-12 documentation handoff (CI/review). Старый #656 закрыт как superseded.

ID ownership: **SX-17 = archive taxonomy (#654); SX-18 = runtime fanout; W6-12 = participant intelligence.** Не менять исторические W6-00…W6-11 / W6F-001…096 IDs.
