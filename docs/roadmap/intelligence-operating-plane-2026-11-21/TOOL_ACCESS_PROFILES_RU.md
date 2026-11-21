# Tool Access Profiles для Studious coding agents и ChatGPT
## Установка, MCP, data residency, доступ и стоимость контекста

**Назначение:** дать coding agent максимальный полезный набор tools, но без взрыва контекста, дублирования индексов и ненужных прав. Инструменты доступны по задаче, а не все одновременно каждому агенту.

---

# 1. Рекомендуемые profiles

| Profile | Tools | Для чего |
|---|---|---|
| LOCAL_CODE | Existing src/intelligence CLI, Git, pytest, Graphify optional sidecar | Код, AST, dependencies, impact, context packs |
| STRATEGY_RESEARCH | LOCAL_CODE + read-only SQD Portal + small Antseer subset | Chain state, providers, flows, venue coverage |
| OPERATIONS_READ | OCA CLI, observability replay/export, AGG-02/MarketEpisode readers, DuckDB optional | Operation trace, paper/shadow, provider metrics, episode compare |
| CODING_WORKER | TASK_PACKET reader, LOCAL_CODE, tests, verifier, WORK_RESULT generator | Одна ограниченная implementation task |
| REVIEWER | Git diff, context pack, test evidence, index diff, task ledger | PR review и strategy impact |
| HUMAN_OPERATOR | Health/status/readiness, reports, explicit approvals | Контроль и одобрение человеком |

MVP включает только LOCAL_CODE, OPERATIONS_READ, CODING_WORKER и REVIEWER. STRATEGY_RESEARCH — по запросу; HUMAN_OPERATOR остаётся у человека.

---

# 2. Инструменты: решение и ограничения

## 2.1 Existing Studious CLI — обязательно

Основной локальный entrypoint:
- python -m src.intelligence.cli repo scan/status/export/delta/benchmark;
- python -m src.intelligence.cli storage status/forecast/rollups/compact/retention-dry-run;
- python -m src.intelligence.cli report build/compare/bundle;
- existing observability replay/export/verify commands;
- existing tests/verifiers.

Агент сначала проверяет фактические argparse commands и help output. Документированный пример команды не означает, что она прошла execution test на новом main.

## 2.2 Graphify — optional code intelligence sidecar

Зачем:
- дополнить Python AST индекс polyglot languages;
- связать code, configs, SQL schemas и documentation;
- queries по call paths, dependencies, impact и tests;
- incremental update вместо полного переиндексирования.

Docs: https://github.com/Graphify-Labs/graphify

Начальная установка в developer environment, не в runtime package:

~~~bash
uv tool install "graphifyy[mcp]"
graphify extract . --no-viz
graphify query "what calls the canonical strategy entrypoint?"
~~~

Перед применением проверить текущий CLI и flags; команды/версии могут меняться.

Правила:
- начать с code-only/local extraction;
- semantic extraction docs/PDFs/images не включать по умолчанию;
- если semantic extraction нужна, backend выбирать явно и проверить data residency;
- сохранить различие EXTRACTED и INFERRED relations;
- Graphify graph остаётся sidecar projection, не заменяет canonical registries;
- cache/build должны быть commit-bound;
- не коммитить graph database/huge binary index.

## 2.3 jCodeMunch — только после license approval

Зачем: symbol-level search/fetch вместо чтения больших файлов.

Docs: https://github.com/jgravelle/jcodemunch-mcp

Dual-use license версии, опубликованной в октябре 2026, разрешает non-commercial use бесплатно, но commercial/revenue-supporting internal use требует paid license. Для revenue-generating flashloan bot не считать его бесплатным. До license decision использовать current context_pack/native AST.

Заявленный vendor token-saving benchmark — собственный 15-lookup comparison на трёх codebases. Не переносить цифру как гарантию для Studious; воспроизвести на golden questions.

## 2.4 SQD Portal MCP — read-only chain research

Endpoint/docs:
- https://portal.sqd.dev/mcp
- https://sqd.dev/learn/portal-mcp-server-setup/
- https://github.com/subsquid-labs/portal-mcp-server

Подходит для bounded historical/recent EVM transactions/logs/traces, Solana transactions/instructions, Bitcoin inputs/outputs, Hyperliquid fills, Substrate events/calls.

Правила:
- read-only research/evidence source;
- точные network + block/slot bounds;
- минимальный field list and bounded row limit;
- следовать pagination cursor;
- сохранять query hash, network, window, coverage, retrieval time, page count;
- не запрашивать всю сеть/огромный time range без причины;
- не считать ответ SQD proof of protocol-specific executable state/finality;
- ingestion в Studious stores — только через existing source governance/schema/provenance/quota/replay.

Docs описывают bounded previews/cursor pagination. Большое окно Solana может вернуть capped page, а не весь набор. Нужно сужать slot range и filters.

## 2.5 Antseer MCP — небольшая аналитическая подсекция

Docs: https://antseer.ai/docs

Документация заявляет 65 read-only tools в 12 domains, provenance на datapoints и возможность ограничить exposed tools URL query. Для single-purpose agent рекомендует менее 10 tools.

Применение: supplemental fund-flow/smart-money/token/protocol analytics, research signal и cross-check market context.

Не использовать как exact pool state authority, executable quote, lending capacity proof, transaction finality proof или production trading authorization.

Не открывать все 65 tools каждому coding agent. Использовать profile с несколькими выбранными tools.

## 2.6 DuckDB + Parquet — optional local analytics

Docs:
- https://duckdb.org/docs/data/parquet
- https://parquet.apache.org/docs/file-format/data-pages/compression/

DuckDB умеет читать Parquet напрямую с projection/filter pushdown. ZSTD поддерживается Parquet. Это может дать local historical queries без обязательной второй database.

Сначала проверить existing analytics dependencies/reports. Не добавлять DuckDB в production runtime package ради research CLI, если хватает analytics extra.

## 2.7 Mimir / growmos — не включать по умолчанию

- Mimir overlaps local memory/code/docs retrieval. Его docs описывают O(n) vector scan по RAM/time; включать только после benchmark на реальной corpus size.
- growmos полезен для shared semantic knowledge/provenance, но не является raw source event store и не заменяет source AST.
- Не разворачивать их одновременно с Graphify и existing Local Intelligence V2 без конкретного gap.

---

# 3. Tool access policy — права и контекст

## 3.1 Capabilities

| Tool group | Read | Write | External side effect |
|---|---:|---:|---:|
| Repo index / context pack | Yes | Только local generated artifacts | No |
| Git inspection | Yes | Branch/worktree commits в task scope | Repo changes |
| Unit/offline tests | Yes | Test artifacts | No market side effect |
| SQD/Antseer | Yes | No | External read queries |
| OCA/observability replay | Yes | No | No |
| Market data collectors | Governed | Through canonical ingestion owner only | RPC/provider reads + storage writes |
| Signing/submission/live controls | Not granted | No | Not allowed |

MCP read-only surface не должен иметь shell/write tools. Coding agent получает normal Git/code write permissions только в isolated worktree. Это разные scopes.

## 3.2 Context budget

Не включать все MCP tools всегда:
- code worker: 1–3 repo/context tools + Git/test shell;
- operations analyst: 3–6 OCA tools + optional data provider subset;
- chain researcher: SQD tools only for task scope;
- reviewer: diff/context/evidence/status, no mutating market tools.

Tool output — compact structured fields, не verbose raw payload. Full records fetch by ID. Если tool вернул next_cursor, агент продолжает осознанно, а не dump-ит все pages.

## 3.3 Credentials and data residency

- No keys/seeds in repo, MCP examples, packs or task packets.
- Environment credential reference only; secret supplied via approved local secret manager.
- No arbitrary remote semantic indexing of proprietary repo by default.
- Graphify code-only mode runs locally without remote LLM backend.
- External MCP responses enter model context only when explicitly queried.
- Record provider terms, license, source host and retention policy before persistent ingestion.

---

# 4. Reproducible installation model

Не vendoring third-party source. Repo should contain:
- pinned tool manifest/config;
- wrappers and adapters;
- test fixtures and benchmarks;
- installation/health-check commands;
- license inventory and source provenance;
- CI cache keys by binary version + checksum.

External tools install into developer environment using approved package manager. Production runtime dependencies remain isolated from optional research/code-index tooling.

Proposed files after W0:
- tools/tooling-profiles.json;
- tools/tool-versions.lock;
- tools/mcp-profiles.example.json;
- scripts/check_tooling_profiles.py;
- docs/tooling/INSTALL_LOCAL_INTELLIGENCE_RU.md.

Не добавлять manifests до проверки exact versions, Python compatibility and licenses.

---

# 5. Tool decision table

| Tool / block | MVP status | Reason |
|---|---|---|
| Existing src/intelligence | Mandatory | Repo snapshot/context/retention/episode/report owners already exist |
| Existing src/observability | Mandatory | Structured events, replay, integrity, export, readiness |
| Existing AGG-02/MarketObservation | Mandatory | Canonical raw market lineage/replay |
| Git worktrees + task packets | Mandatory | Current human+coding-agent stage |
| Graphify | Benchmark first | Potential polyglot coverage gap in current Python index |
| SQD Portal | Research profile | Read-only bounded cross-chain evidence |
| Antseer | Research profile subset | Supplemental analytics; expose few tools |
| jCodeMunch | License-gated | Commercial license needed for revenue-supporting workflow |
| DuckDB | Optional analytics extra | Query Parquet locally if current reports insufficient |
| Mimir | Deferred | Overlap and vector-scan scaling |
| growmos | Deferred | Semantic multi-agent knowledge not yet required |
| ClickHouse | Scale-gated | Only if measured operational event/query volume exceeds current stores |
| NATS JetStream | Deferred | No distributed consumer fanout requirement proven |
| Remote MCP gateway | Deferred | First stabilize local CLI and bounded query contracts |
| Autonomous orchestrator | Deferred | Human + coding agents currently sufficient |

---

# 6. Required tool-access audit in W0

Coding agent must report:
1. Which current CLI commands actually work on fresh main?
2. Which requirements already cover Parquet/analytics/reporting?
3. Which local tools are installed and which need installation?
4. Does repo build complete Python symbols/call relationships?
5. Which languages and config formats remain uncovered?
6. Is Graphify MCP useful compared with native context_pack?
7. Do SQD and Antseer profiles return bounded/provenance-backed data under selected tool subsets?
8. Are there licensing blockers for jCodeMunch or any semantic indexer?
9. What minimal MCP/tool profile exposes enough capability without tool catalog explosion?
10. What measured token reduction and latency results come from the golden query set?

No agent should claim access to a tool until install/connection and a read-only self-check succeed.
