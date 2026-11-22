# Readiness DAG: CAPTURE_ONLY → exact market → paper

## Краткий DAG

\`\`\`text
LATEST MAIN + PR/OWNER RECONCILIATION
              |
              v
#679 CAMPAIGN_START + WINDOWS P0 (GATE-01 / WIN-01)
              |
              +---- SOURCE DOSSIER + SOURCE-ID CROSSWALK (GATE-02)
              |
              +---- DURABLE SOURCE INTAKE / RAW EVIDENCE (DATA-01)
              |
              +---- IF ROOTED-STATE READS ARE IN SCOPE: INDEPENDENT RPC QUORUM (RPC-01)
              |
              +---- ASSET/MINT/TOKEN-2022 IDENTITY (ASSET-01)
              |
              +---- DISCOVERY / QUOTA / COVERAGE (DISC-01)
              |
              v
HUMAN OPERATOR APPROVAL OF EXACT MANIFEST + PROFILES + BUDGET
              |
              v
CAPTURE_ONLY (NO TRADE) --> OFFLINE REPLAY + COVERAGE RECEIPT
              |
              +--> no rooted RPC: discovery-only; rooted verdict remains BLOCKED_SINGLE_SOURCE
              |
              +--> rooted state reads: RPC-01 PASS + exact context/hash agreement
                                  |
                                  v
EXACT MARKET STATE + AMOUNT-SPECIFIC DIRECT QUOTES
(CPMM #659; CLMM/DLMM #660; route dedup; PR118 size grid)
              |
              +-------------------------+
              |                         |
              v                         v
       R02 CAPITAL PROOF          R03 BUILDER PROOF
       (#677 OR #678 OR #669)     (MATCHING SAME LENDER)
              |                         |
              +-------------+-----------+
                            v
                    R04 CANDIDATE SELECTOR
                            |
                            v
                    R05 EXACT FULL MESSAGE
                            |
       W10 EVENT PRODUCERS + PAPER DURABILITY/FAULT TESTS
                            |
                            v
                 INSTALLED COMPOSITION + QPR/R06
                            |
                            v
             OPTIONAL/APPLICABLE MPR-05 72H SOAK
                            |
                            v
               SENDER-FREE PAPER QUALIFICATION
\`\`\`

## Что действительно блокирует первый CAPTURE_ONLY

| Gate | PASS evidence | Не является заменой |
|---|---|---|
| CAMPAIGN_START CS-01..CS-10 | staged PREFLIGHT_PASS → CAPTURE_AUTHORIZED → CS06_PENDING_CAPTURE → CAMPAIGN_QUALIFICATION_PASS; exact signed manifest/profile/config/code/source/policy/budget binding | документация #671, ручная проверка строк, environment boolean; CAPTURE_AUTHORIZED ≠ qualification PASS |
| Source readiness | свежий official docs/ToS/license/schema/auth/quota/profile; current generation; source ID crosswalk | HTTP 200, старый checked_at, неизвестная ToS |
| Source intake/evidence | raw bytes or exact retained reference, request fingerprint, hash, source generation, cursor/gaps, attempts, latency, typed errors, replay | только normalized candidate list |
| RPC role | Для discovery-only CAPTURE_ONLY rooted quorum не нужен, если rooted reads исключены из manifest. Для любого rooted snapshot обязательны 2 independent operators/correlation groups, same genesis, finalized context, slot/skew/hash evidence | две API keys или два endpoint у одного operator |
| Asset identity | pre-capture safe parser/provenance/typed-unknown handling; HARD_BOUND mint/program/decimals/Token-2022 + pool/vault identity is mandatory before exact quote/route admission | ticker, symbol, registry reference decimals; treating every discovery candidate as HARD_BOUND before discovery capture |
| Budget/retention | enforced durable attempt/storage limits across process restarts, replay, rollback and quota attribution | config field not enforced at write boundary |
| Platform | native Windows verification receipt when Windows is deployment target | Linux CI alone or historical receipt |
| Human approval | explicit authorization for this exact immutable manifest/profile set/budget | merge of docs PR, agent instruction, prior authorization |

**Important qualification nuance:** discovery-only collection can be explicitly classified separately from rooted-state qualification. If rooted reads are excluded from the approved manifest, missing RPC quorum does not block discovery-only capture. Any single-source observation remains exploratory/\`BLOCKED_SINGLE_SOURCE\` and cannot support a rooted-state verdict. Do not silently promote it. CS-06 actual non-synthetic source evidence is a post-capture proof, not a pre-network prerequisite; \`CAPTURE_AUTHORIZED\` is not campaign qualification PASS.

## Что не блокирует сбор discovery, но блокирует exact market / paper

- RPC-01 rooted quorum: не блокирует discovery-only capture без rooted reads; обязателен до любого rooted-state verdict. Если есть только один источник, оставить BLOCKED_SINGLE_SOURCE.
- R02 lender capacity: не нужен для первого read-only discovery capture; нужен before executable financing edge.
- R03 builder conformance: не нужен для discovery; нужен для same lender resource and actual route.
- R04/R05: не нужны для CAPTURE_ONLY; обязательны before paper.
- W10 EventEnvelope production producers: may be parallelized and are required for truthful ongoing operations/paper observability; do not mistake #676 projection for event production.
- R06/QPR + installed paper composition: исключительно paper gate.
- MPR-05 72h: separate installed qualification soak if applicable; not a synonym for 24h market data observation.

## Source role classification

| Source family | First-wave role | Admission rule |
|---|---|---|
| DEX Screener, GeckoTerminal | discovery | source contract + quotas fresh; pool/mint verified separately |
| Raydium API V3, Meteora Data API | discovery metadata | not executable depth; route exact state via direct RPC |
| Solana RPC | rooted direct accounts | two genuinely independent profiles and coherent finalized evidence |
| Jupiter V2, 0x | route comparators | same raw amount/pair/time window; no pool independence claim without physical lineage |
| Helius/Yellowstone/gRPC/shreds | change trigger / stream evidence | not replacement for complete rooted state closure |
| Pyth/Switchboard/CEX | reference/signal | not DEX executable quote |
| Flash lenders | capital resources | one resource at a time; rooted resource capacity + matching R03 builder |
| Jito/Helius Sender/Astralane/bloxroute/0slot | disabled delivery research | no paper prerequisite; no send/tip/activation |

## Core metrics

Keep populations separate and show numerator + denominator:
- discovered markets by source/family;
- identity-verified assets and pools;
- alias/physical pool dedup counts;
- rooted state-complete pools with per-provider context slots;
- exact quotes × venue × direction × raw input amount;
- complete routes and each typed rejection class;
- all-in positive/negative economics; unknown-cost population;
- qualified lender resources and amounts; builder-conformant plans;
- R04 candidate count; R05 full-message simulation pass/fail;
- paper attempts, durable terminal outcomes, UNKNOWN terminal count, restart/replay divergences;
- API calls, physical attempts, throttles, latency, freshness, slot skew, dropped/gapped events, bytes/retention and replay network calls.

No aggregated success percentage without the denominator and evidence class (fixture/replay/live read-only/paper).


## Уточнение стадий и обязательных критериев v1.1

### CAMPAIGN_START / CS-06

- `PREFLIGHT_PASS`: только offline/pre-network CS checks, digest/generation binding и проверенная Ed25519 operator authorization для точного manifest/profiles/budget. Транспорт ещё не открыт; реальное наблюдение CS-06 здесь не подменяется fixture.
- `CAPTURE_AUTHORIZED`: разрешены только ограниченные read-only calls из подписанного manifest. Это не `CAMPAIGN_QUALIFICATION_PASS`, не exact-market и не paper.
- `CS06_PENDING_CAPTURE`: ожидание durable фактического non-synthetic observation. Docs, fixtures и synthetic responses не удовлетворяют этому условию.
- `CAMPAIGN_QUALIFICATION_PASS`: только после реального capture evidence и всех применимых CS gates. Rooted-state verdict дополнительно требует `RPC-01`; discovery-only manifest без rooted reads не требует quorum.

### Asset identity: safe discovery vs HARD_BOUND

`ASSET-01` до capture проверяет способность безопасно разбирать, сохранять и классифицировать mint/program/decimals/Token-2022/pool identity и неизвестные значения. Это не означает, что каждый обнаруженный кандидат обязан быть `HARD_BOUND` до discovery-only capture. Неизвестные кандидаты сохраняются как `UNKNOWN/BLOCKED`, но не допускаются к exact quote или route. Для `HARD_BOUND` обязательны актуальные доказательства mint owner/token program/decimals/extensions, genesis и canonical pool/token-order/vault identity.

### Exact-market admission contract

Для каждого допускаемого CPMM/CLMM/DLMM pool и направления обязательны:

1. Полное venue-specific account closure (включая reachable tick arrays / BinArrays, bitmap, observation, dynamic-fee, clock/epoch, vault, mint и Token-2022 dependencies по применимости).
2. Отдельный direct quote для каждого raw input amount из PR118 grid; запрещены interpolation, scaling и extrapolation.
3. Физическая идентичность и dedup через R13-K; alias/aggregator/comparator route не считается независимым пулом или ликвидностью.
4. Coherent genesis, per-response context slots, account/state hashes, source generation, observation time, freshness bound и expiry для каждой зависимости.
5. Полный all-in economics per route × amount: swap/token/flash fees, разрешённые modeled priority/tip/compute/rent/provider/failure costs и остатки. Любой UNKNOWN cost, stale/mixed state или unsupported token behavior блокирует admission.

Эти требования — acceptance contract существующих владельцев #659/#660, R13-K и PR118; они не разрешают создавать дублирующие quote engines, deduplicator или size solver.
