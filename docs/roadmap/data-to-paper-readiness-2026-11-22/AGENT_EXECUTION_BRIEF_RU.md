# Полный execution brief: от подготовки live-data campaign до sender-free paper qualification

**Дата:** 2026-11-22  
**Проверенный baseline main:** \`0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54\`  
**Режим:** документационный assignment pack; никаких runtime-изменений этим PR не заявляется.

## 1. Миссия и границы

Довести существующую систему до доказуемой последовательности:

\`source discovery → governed CAPTURE_ONLY → canonical identity → rooted state → exact amount-specific quotes → route/resource qualification → R02 capital + R03 unsigned builder → R04 selection → R05 exact full-message simulation → installed R06/QPR paper qualification\`.

Не строить новый бот, market-data plane, transport, RPC client, graph, route solver, paper runner, journal или execution kernel. Найти фактических owners в текущем main и расширять их на месте.

Разделять три независимых результата:

1. **CAPTURE_ONLY / data qualification** — можно собрать discovery, source-quality и разрешённые read-only observations, если CAMPAIGN_START и операторская авторизация PASS. Это не доказывает exact liquidity, flash capacity, route profitability или paper readiness.
2. **EXACT_SHADOW_CANDIDATE** — точное состояние, identity, direct quotes, size grid, физическая независимость пулов и net economics. Это ещё не paper PASS.
3. **PAPER_QUALIFICATION** — только установленный canonical sender-free runtime после R02+R03+R04+R05 и точного R06/QPR/campaign-authority PASS. Никаких custom loops или fake fills.

Важно: R02/R03/R05 не являются prerequisites для первого ограниченного CAPTURE_ONLY discovery-цикла. Они обязательны до квалификации полного route и paper. И наоборот, успешный CAPTURE_ONLY ни при каких условиях не разрешает paper или live. CAMPAIGN_START обязан разделять \`PREFLIGHT_PASS\` (только pre-network checks + проверенная подпись точного manifest), \`CAPTURE_AUTHORIZED\` (разрешение только на перечисленные bounded read-only calls), \`CS06_PENDING_CAPTURE\` (ожидание фактического non-synthetic evidence) и \`CAMPAIGN_QUALIFICATION_PASS\`. \`CAPTURE_AUTHORIZED\` не равен qualification PASS; CS-06 не может быть закрыт fixture/docs/synthetic response. Rooted RPC quorum — отдельное условие RPC-01 только для manifest/вердиктов, которым действительно нужен rooted state.

## 2. Сначала зафиксировать актуальное состояние

Перед любой реализацией:

- Прочитать \`AGENTS.md\`, root \`CODEX_START_HERE.md\`, \`docs/roadmap/agent-execution-master-2026-11-13/CODEX_START_HERE.md\`, \`MULTI_AGENT_EXECUTION_PLAN.md\`, \`PROJECT_KNOWLEDGE_BASE_MAP.md\`, \`TASK_INDEX.md\`.
- Fetch latest \`origin/main\`, точный SHA, tree, рабочее дерево, весь открытый PR inventory, changed paths, reviews и CI. SHA в handoff ниже — только audit baseline.
- Перечитать текущие campaign docs: \`docs/roadmap/paper-data-campaign-universe-2026-11-21/\`, \`docs/roadmap/campaign-start-preflight-2026-11-21/\`, \`docs/roadmap/live-data-qualification-2026-11-21/\`, CLMM/DLMM runbook и R06 task.
- Пересверить #679 CAM-01..05 с этим backlog; #679 остаётся владельцем campaign gate и Windows runtime fixes.
- Пересверить #666 + OCA-W0/#680, W0A/#681, W0C/#682. Эти аудитные PR не являются implementation и не дают права объявить граф, event plane или live-data pipeline готовыми.
- Пересверить #665, #667, #669, #670, #671, #677, #678 и PR #672–#676 на актуальную базу и changed paths. Не переписывать их владельцев и не считать open PR доказательством завершения.
- Внести каждую обнаруженную новую проблему в \`TASK_BACKLOG_V1.json\` с root cause, exact owner path, тестом, dependency и acceptance criteria. Не оставлять findings только в комментарии агента.

### Repo-intel / graph tools

Если в локальной среде coding agent реально подключён repo-intel MCP, работающий knowledge graph и incremental indexer — используй их для поиска owners, callers/callees, тестов, конфигов, provider/strategy lineage и PR collisions; приложи измеримый receipt (tool/version, repo SHA, запрос, найденные refs, freshness).

Не заявляй, что MCP использован, если сервер не подключён или вызов не состоялся. В этой ChatGPT-сессии отдельный repo-intel MCP connector не был доступен. В этом случае используй существующие repository-native intelligence/context owners и доказательства #680–#682; отсутствие MCP фиксируй как tooling limitation, не блокируя Web3 работу и не создавая параллельный граф. #666 прямо говорит, что W0B и полный runtime graph пока не реализованы.

## 3. Неприкосновенные правила

- Все task PR — отдельные branch/worktree, один task ID, один canonical owner, один reviewable PR. Никакого общего shared checkout или параллельного редактирования одного owner-файла.
- Кодовые worktrees создаются от latest main. После слияния dependency PR — rebase/fresh CI; не пытаться массово сливать пачку веток.
- Внешние контракты: checked-in dossier first, затем официальная документация и upstream. Фиксировать URL, retrieval UTC, API/SDK version, commit/blob SHA, license/ToS, schema/IDL, единицы, decimals, rounding, quota, auth и ошибки. Смена схемы создаёт новую immutable dossier generation.
- Discovery metadata ≠ exact pool state; ticker ≠ mint identity; aggregator route ≠ независимый pool; TVL/vault cash ≠ flash-borrow capacity; documentation ≠ live evidence; fixture ≠ live; quote ≠ executable transaction; simulation of legs separately ≠ simulation of final whole message.
- Unknown остаётся UNKNOWN/BLOCKED. Нельзя заменить отсутствие данных нулём, синтетическим успехом, default freshness, фиктивным fill или операторской boolean-переменной.
- Сохранять все кандидаты, включая stale, incomplete, alias, rejected, no-route, no-trade и negative economics.
- Нельзя включать provider, использовать платный тариф, проверять credentials, создавать account/ATA/obligation/position, подписывать, отправлять, занимать, тратить, давать relay tip, деплоить или менять production authority.
- \`sign_enabled=false\`, \`send_enabled=false\`, \`live_enabled=false\`, \`execution_authority=NONE\`, production live hard-denied. Ни один assignment ниже не меняет эти значения.
- Никогда не запускать CAPTURE_ONLY из PR/CI/agent task без отдельной явной операторской авторизации конкретного manifest/profiles/budget. Этот PR — только план.

## 4. Порядок исполнения

### Wave A — до первого разрешённого CAPTURE_ONLY

P0 задачи:

1. Закрыть campaign control-plane через #679: executable CS-01..CS-10 gate до открытия транспорта, digest binding, source generations, operator authorization, bounded attempts/storage, sender-free RPC allowlists, negative tests.
2. Проверить официальные docs/ToS/лицензии, auth mode, endpoint, schema, quota, retry policy, source/operator/correlation group, TTL и IDs для каждого включаемого источника. Сопоставить \`DiscoveryRequest\`, source catalog, provider registry и campaign source dossiers; aliases не переименовывать эвристически.
3. Доказать, что разрешённый source intake пишет raw payload/request fingerprint/response hash/cursor/gaps/каждый физический attempt/latency и typed rejects в существующий durable evidence owner и воспроизводится offline. Cursor allocation, append и attempt reservation должны быть сериализованы на canonical owner boundary; проверить multi-process append race, duplicate/retry, partial write, DB/WAL recovery и restart. Повторное получение не должно создавать потери или скрывать save errors.
4. Разделить discovery-only, poll-only, stream-trigger и rooted-state source capabilities. Если stream-производителя нет — честно указать POLL_ONLY/ONE_SHOT/UNAVAILABLE; не писать STREAMING по факту наличия SDK.
5. Проверить deployment-provided operator profiles. RPC-01 обязателен для manifest с rooted-state reads и для любого rooted verdict: минимум два действительно независимых RPC operator/correlation groups, один genesis, finalized/rooted commitments, отдельный per-response context slot, minContextSlot/skew policy и одинаковые account hashes либо typed disagreement. Если rooted reads исключены из manifest, отсутствие quorum не блокирует discovery-only CAPTURE_ONLY; single-source observations остаются exploratory/\`BLOCKED_SINGLE_SOURCE\` и не поддерживают rooted verdict. Shared/public RPC — только exploratory; несколько endpoint/API keys одного operator не дают rooted quorum.
6. До capture доказать безопасную обработку identity: парсинг и сохранение mint/program/decimals/Token-2022/pool fields, provenance и typed unknowns. Не требовать HARD_BOUND для каждого discovery candidate: неразрешённый кандидат сохраняется как UNKNOWN/BLOCKED и не допускается к quote/route. Перед exact quote/route каждый admitted asset/pool обязан получить HARD_BOUND на основании актуальных owner/token-program/decimals/extensions evidence, chain genesis, venue program/deployment, pool address, token ordering и vault identity. Старый registry/ticker/reference decimals — только подсказки.
7. Сделать native Windows verification частью фактического Definition of Done: #679 WIN-01..04 и platform receipt с реальным OS Caption/DisplayVersion/build/arch, Python 3.13 x64, uv lock markers, Proactor/socket fixture, SQLite close lifecycle. Не ослаблять сетевую изоляцию ради зелёного pytest.
8. Исправить или изолированно классифицировать baseline test defects: после исправления Proactor запускается повторный baseline; отдельно расследовать GPR unresolved synthetic paths и CRLF/hash/environment failures. Не списывать реальные assert failures как environmental без воспроизведения.

Разрешённый campaign manifest перед запуском должен иметь привязку к latest main, runtime-authority generation, policy/source registry, source dossiers, operator profiles, budget/retention и hash. Нет валидной подписи/проверяемого оператора — BLOCKED; не изобретать самодельную схему approval.

### Wave B — bounded CAPTURE_ONLY и воспроизводимость

- Только после Wave A + явного оператора: ограниченная discovery/read-only capture с зафиксированными profiles, endpoints, quotas, timeouts, rate/backoff, attempts, max bytes, retention и rollback.
- SOL/USDC — лишь поисковая подсказка; не предполагать существование пары/пула. Не концентрировать сбор на одном pair/provider; использовать campaign diversity и negative-control fraction из manifest.
- Сохранять raw request/response, SHA256, source generation, UTC retrieval, chain genesis, pool/program ids, response/context slots, freshness, cost/attempt count, schema version и typed decision.
- Discovery providers (DEX Screener, GeckoTerminal, Raydium API, Meteora Data API) не являются direct depth/price proof. Jupiter/0x — comparison routes, не независимые pool liquidity. Oracle/CEX feeds — reference/signal-only; shred/gRPC/stream feeds — change trigger, а не rooted state.
- Каждая batch read сохраняет собственный context slot. Не синтезировать общий slot для нескольких RPC responses.
- После capture — replay из retained evidence с нулём outbound network calls, digest equality, coverage denominator и explicit missing-source report. Replay не смешивать с live. Фактическое CS-06 evidence подтверждается только сохранённым non-synthetic observation; его не заменяют fixture/docs. Если rooted reads не входили в manifest, результат остаётся discovery-only, без rooted-state claim.

### Wave C — exact market evidence

- CPMM reuse: #659 \`src/strategy/cpmm_cycle_binding.py\`.
- CLMM/DLMM reuse: merged #660 owners \`src/providers/raydium_clmm_native.py\`, \`src/providers/meteora_dlmm_native.py\`, \`src/strategy/clmm_dlmm_binding.py\`, \`scripts/clmm_dlmm_market_trace_replay.py\`. Не дублировать эти owners.
- Закрыть полное venue-specific state closure: CPMM reserves/vaults и применимый fee state; Raydium CLMM pool/config/observation/bitmap/all reachable directional tick arrays/dynamic-fee dependencies; Meteora DLMM pool/bitmap/all reachable directional BinArrays плюс clock/epoch/dynamic-fee dependencies; во всех случаях — mint/vault/Token-2022 state. Missing dependency account = typed rejection. Live differential vectors допускаются только при отдельной авторизации и coherent rooted data.
- Для каждого admitted direction × каждого raw input amount в PR118 grid требуется собственная точная direct quote от canonical venue owner: no interpolation/scaling/extrapolation и никакого reuse quote от другого amount/state. Записать consumed input/output, fee components и denominations, ticks/bins/arrays, block time/epoch, decoder/quote revision, state generation/hash, source slots, freshness threshold, expiry и typed rejection.
- Route admission через существующие MarketObservation → graph ingest → #659 route binding → R13-K physical pool/resource dedup → PR118 amount grid → all-in economics. Physical identity должна исключать alias/повтор одного pool/resource; aggregator/comparator route не является независимой ликвидностью. Не создавать второй solver/deduplicator.
- Economics обязательна для каждого route × amount и включает swap/token/transfer fees, flash fee, priority fee, tip только если он включён в разрешённую модель, CU/compute, rent/account setup, provider charges, failure/revert cost и остатки. Каждая котировка привязана к coherent genesis/per-response slots/account hashes/source generation/observation time/freshness bound/expiry. UNKNOWN cost, stale/mixed state или unsupported token behavior = BLOCKED; никакого positive-net claim.
- #665 repairs принадлежат только #665. Не переносить vendor mirror, CSV или source manifests в эту задачу.

### Wave D — lender/build/selection/simulation vertical

- Продолжить отдельные lender owners: #677 Jupiter Lend N06, #678 Project 0 N07, #669 Kamino N08. Это конкурирующие независимые provider lanes, а не 3 обязательных lender-а для первой paper вертикали.
- Для первого paper path нужен хотя бы один реально квалифицированный ресурс: rooted reserve/bank/vault state, deployed owner/version, mint/decimals, liquidity/debt ceiling/limits, utilization/liabilities, exact fee+rounding, eligibility, slot/freshness и независимая provenance. Если ни один не прошёл, paper = BLOCKED.
- Его парный R03 unsigned builder обязан доказать principal/mint equality, borrow/repay bookends, exact callback/hot-potato semantics, account metas/order, program versions и отсутствие account creation. Offline-built ≠ conformance PASS.
- R04 использует существующий candidate selector; допускает только exact supported route + qualified capital resource + builder + net economics. Не добавлять обходную ручную approval boolean.
- R05 симулирует **тот же полный финальный message/PTB**, включая borrow → route → repay, compute budget, fees/tip/rent и все account metas, при тех же state-generation fingerprints. Отдельные swap simulations недостаточны. Reconciliation подтверждает exact repayment, token balances, residuals и all-in result.
- Sui NAVI/DeepBook и EVM не добавлять в первый Solana paper path без отдельного chain-local proof. #667 — отдельная Sui lane; не смешивать результаты с Solana.

### Wave E — observability, installed paper и soak

- Принять вывод #680: на проверенном main \`make_event()\` production callsites = 0; producer→store→export→replay отсутствует. Не считать OpenLineage projection (#676) runtime producer.
- Оформить W10 producer wiring через текущий EventEnvelope/ObservabilityStore/AGG-02/MarketObservation/MarketEpisode owners: discovery, quote, candidate, route, capital, build, simulation, decision, terminal, reject, cancellation и restart события. Event runtime/version/environment должны быть реальными, не test defaults. Event IDs/attempt generations idempotent.
- В каждом supported strategy/provider/venue/financing path проставить WIRED/PARTIAL/NO_RUNTIME_PATH/BLOCKED/UNKNOWN и evidence refs. Не обещать полную поддержку из одного demo path.
- Собрать установленный paper runtime только через текущие \`build_paper_shadow_runtime\`, canonical installed paper service, durable lifecycle/journal/reconciliation и соответствующие QPR owners. Никакого собственного while loop, custom paper runner или fake fills.
- R06/QPR-01/02/03 и campaign authority обязаны вернуть точный PASS на одном pinned main/config/source generation. Все admitted attempts имеют durable terminal outcome; UNKNOWN terminal = fail.
- Пройти отказные сценарии: provider outage/quota, loss of RPC quorum, source/schema drift, stale/mixed state, clock/slot skew, duplicate/retry, DB lock/corruption, restart/cancel/backpressure/storage limit, shutdown drain, no-route и replay divergence.
- MPR-05 installed 72-hour soak — отдельный gate, если он применим к данной release path. 24h market observation и CAPTURE_ONLY не заменяют 72h installed paper qualification и не доказывают прибыльность.

## 5. First-wave strategy scope и отложенные линии

Для первой доказуемой Solana vertical сначала предпочесть действительно подключённые same-chain local-atomic families CPMM и exact CLMM/DLMM, при условии source/state/lender/build/simulation proof. Весь discovered universe сохраняется в исследовательском графе; route qualification разрешает только точно доказанные subsets.

Параллельно, но не блокируя первый CAPTURE_ONLY: N01 per-venue Prop-AMM dossiers; N02 event→after-state experiment; N03 stablecoin anchors; N04 Pump migration state; N05 OpenOcean schema drift; N10 Save/Solend support proof; N11 delivery benchmark dossiers. Delivery providers остаются disabled/research-only и не нужны для sender-free paper.

Позже/отдельные gates: CLOB/orderbook one-tx settlement; liquidation same-tx closure; Sui NAVI/DeepBook checkpoint/PTB; EVM pilot; cross-chain/non-atomic hedges. Не смешивать их с локальной atomic arbitrage и не блокировать ими первый Solana capture.

## 6. DoD для каждого implementation PR

Каждый task owner сдаёт:
- exact current base SHA, exact changed paths и один declared canonical owner;
- официальные source pins/versions/license/retrieval time, либо typed blocker;
- positive + negative tests, offline replay, deterministic digest where relevant;
- Windows-native result для platform-affecting changes;
- exact test command, pass/fail/skip/error counts, failing IDs и platform;
- source/campaign evidence receipt, budgets and no-secret proof;
- статусы IMPLEMENTED / VERIFIED_OFFLINE / VERIFIED_LIVE_READ_ONLY / BLOCKED / UNKNOWN — никогда не смешивать;
- PR URL, dependencies, reviewers, merge blocker и next task.

Координатор поддерживает единый status ledger; merge — только после независимого review/CI и явного human approval согласно AGENTS.md. Никаких автоматических merges.

## 7. Финальная точка готовности

**Можно запросить первый CAPTURE_ONLY** только когда все GATE/CAPTURE P0 prerequisites PASS и operator отдельно authorizes exact manifest/profiles/budget.  

**Можно начать sender-free PAPER_QUALIFICATION** только когда Wave C + хотя бы один полный R02/R03 pair + R04 + R05 + W10 observability + installed composition + QPR/R06/campaign authority PASS; MPR-05 soak — по его применимости.  

**Это не live readiness.** Любая live submission/canary/borrow/deployment требует совершенно отдельного human-approved release gate и не входит в этот PR.
