# Fastest Path to Qualification Campaign

## Phase 0 — 1–2 PR: запустить безопасный real-data capture

### A. Canonical Campaign Identity
- один `RuntimeAuthority` digest;
- `CampaignManifest` содержит git SHA, policy digest, source generations;
- sender/signer unreachable;
- stale PR queue не входит в runtime identity.

### B. Qualification Data Plane
- `ProviderProfile` вместо hardcoded URLs;
- native collector принимает rooted snapshot provider;
- independent quorum: provider + operator + correlation group;
- public Solana RPC только smoke/fallback capture;
- single source разрешён, но verdict = `BLOCKED_SINGLE_SOURCE`.

После этого можно запускать campaign и уже находить реальные проблемы.

## Phase 1 — быстрый source fan-in

Подключить discovery-only источники, у которых дешёвый/бесплатный read path:
- DEX Screener;
- GeckoTerminal;
- Jupiter Free;
- Meteora DLMM indexed API;
- Raydium metadata API;
- Helius Free как один RPC/WSS provider;
- любые будущие источники через `FREE-SOURCE-001..064`.

Discovery lane делает только:
1. pool/pair discovery;
2. liquidity/volume/reference signals;
3. venue labels;
4. candidate scoring;
5. no exact profitability claim.

## Phase 2 — exact verification

Для каждого candidate pair:
- resolve venue/program/pool/mints;
- fetch exact rooted state from independent RPC quorum;
- decode reserve/ticks/bins/orderbook;
- apply Token-2022 and fee semantics;
- attach oracle/protocol context;
- compute amount-coupled local quote;
- compare with independent/reference implementation when possible.

## Phase 3 — continuous 24h problem campaign

24h run — не production soak. Цель:
- поймать rate limits, timeouts, schema drift;
- измерить source coverage;
- увидеть gap/reconnect behavior;
- собрать negative/no-trade distribution;
- понять, какие venue families реально дают data completeness;
- выявить storage/quota bottlenecks.

## Phase 4 — Project0 + venue rebind

Project0/MarginFi остаётся BLOCKED до current deployment dossier. Параллельно добавлять venue families по одной: Raydium CPMM → Raydium CLMM → Meteora DLMM → Orca → Phoenix/OpenBook.

## Phase 5 — 72h release-bound soak

Только после source/deployment/cost/persistence closure. 72h evidence связывается с exact wheel/image/config/policy/source generations и не открывает live автоматически.
