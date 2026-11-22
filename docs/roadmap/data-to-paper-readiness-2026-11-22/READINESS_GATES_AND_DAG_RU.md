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
| CAMPAIGN_START CS-01..CS-10 | executable gate до transport open; manifest/source/profile/config/code hashes; verified operator approval; budgets | документация #671, ручная проверка строк, environment boolean |
| Source readiness | свежий official docs/ToS/license/schema/auth/quota/profile; current generation; source ID crosswalk | HTTP 200, старый checked_at, неизвестная ToS |
| Source intake/evidence | raw bytes or exact retained reference, request fingerprint, hash, source generation, cursor/gaps, attempts, latency, typed errors, replay | только normalized candidate list |
| RPC role | Для discovery-only CAPTURE_ONLY rooted quorum не нужен, если rooted reads исключены из manifest. Для любого rooted snapshot обязательны 2 independent operators/correlation groups, same genesis, finalized context, slot/skew/hash evidence | две API keys или два endpoint у одного operator |
| Asset identity | exact mint/program/decimals/extensions and venue/pool/vault identity | ticker, symbol, registry reference decimals |
| Budget/retention | enforced durable attempt/storage limits across process restarts, replay, rollback and quota attribution | config field not enforced at write boundary |
| Platform | native Windows verification receipt when Windows is deployment target | Linux CI alone or historical receipt |
| Human approval | explicit authorization for this exact immutable manifest/profile set/budget | merge of docs PR, agent instruction, prior authorization |

**Important qualification nuance:** discovery-only collection can be explicitly classified separately from rooted-state qualification. If only one RPC is available, do not label result rooted or quorum-verified; record \`BLOCKED_SINGLE_SOURCE\`. Do not silently promote it.

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
