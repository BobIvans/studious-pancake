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
- `CODEX_STRATEGY_EXPANSION_START_HERE.md` — agent entry assignment for THIS pack only.

## Binding non-goals

- No live signing, wallet creation, borrow, transaction submission, Jito sender, production promotion or env-flag bypass.
- No assumption that symbol pairs, TVL, aggregator route labels, oracle prices, bridge flows or historical correlations are executable markets.
- No cross-chain bridge/CEX/perpetual holding period represented as one atomic flashloan route.
- No Robinhood Stock Tokens or tokenized equities.
- No copied third-party SDK/code without license and revision review.
- No duplicate graph, solver, asset registry, market database, correlation ledger, journal, capital graph, admission authority or execution pipeline. Extend canonical owners.
- No PR auto-merge. Every implementation slice must be a reviewable PR and remain unmerged until repository owner approval.

## How to use

Place this directory in the repository as-is. Agents should start from `CODEX_STRATEGY_EXPANSION_START_HERE.md`, read the source files above, refresh all statuses against current main and active PRs, then execute independent work packages in parallel only where ownership/dependencies permit. The pack must remain an additive overlay: the active market-integration assignment is owned by its existing agents.


## Research expansion v2 from accessible parallel-chat history

After SX-00 reconciliation (#639), an additional pass over accessible saved conversation/archive extracts identified further mechanisms and research families. Added:
- STRATEGY_RESEARCH_ARCHIVE_ADDENDUM_RU.md — SX-17…SX-25, DP-01…DP-08 dataset plan, owner mapping and dependency plan.
- STRATEGY_RESEARCH_ACCEPTANCE_MATRIX_V2.json — machine-readable additive overlay; v1 remains unchanged.
- SX-17…SX-25 appended to STRATEGY_EXPANSION_ASSIGNMENTS_RU.md.

Read the v2 addendum after SX-00. Historical extracts are not complete server-side transcripts of every parallel chat; SX-24/SX-25 therefore preserve ongoing source/strategy discovery without duplicating canonical owners or auto-qualifying ideas.
