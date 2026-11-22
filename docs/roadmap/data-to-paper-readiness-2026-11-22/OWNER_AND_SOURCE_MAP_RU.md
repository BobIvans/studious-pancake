# Owner map, existing PR reconciliation and official source map

## 1. Current baseline and assignment boundaries

Checked \`main\`: \`0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54\` (2026-11-22 audit). This is the base used for this docs task pack; workers must re-fetch main before coding.

| Existing owner / PR | Canonical responsibility | Assignment rule |
|---|---|---|
| #679 | executable CAMPAIGN_START CS-01..10, source/runtime generation binding, campaign budgets, sender-free RPC allowlists, native Windows hardening | Continue its CAM/WIN tasks; this PR adds downstream readiness contracts, not a duplicate implementation |
| #671 | hash-bound V2 capture manifest, CS-01..10 manual map, RPC profile templates, source recheck matrix | Treat as campaign-preflight docs/templates; a script must execute the gate (#679) |
| #670 | Windows smoke receipt + historical pytest classification | Receipt is not a fix; #679 owns lock/Proactor/SQLite fixes and native rerun |
| #666 | knowledge graph / Web3 R&D design and agent handoff | Design-only until implementation; W0B follows the three parallel audits |
| #680 / #681 / #682 | W0 owners/event correlation audit, W0A deterministic retrieval benchmark, W0C source/provider/strategy data-path inventory | Read-only/benchmark audits; feed exact findings into W0B and W10 without repeating audits |
| #665 | Prop-AMM/pmm-sim mirrors, local harness, caller profile and evidence | Same-branch repairs for its verifier failures; do not duplicate vendor/evidence owner |
| #667 | Sui/Aftermath quote/state ingestion | Separate Sui lane; not a Solana first-wave exact route |
| #669 / #677 / #678 | Kamino N08, Jupiter Lend N06, Project 0 N07 R02/R03 evidence/implementation | Separate lender lanes; at least one complete resource+matching builder required before paper |
| #660 merged / #659 merged | CLMM/DLMM exact quote and mixed-route binding / CPMM cycle binding | Preserve owners; follow-up tests/official differential only, no duplicate quote kernel |
| #672 / #673 / #676 | schema compatibility / metadata catalog / OpenLineage projection | Coordinate shared schema registry path and rebase; none supplies missing runtime producers |
| #674 / #675 | Debezium/NATS adoption records | NOT_REQUIRED_YET; do not add these services unless measured requirement changes |

All open PRs must be freshly fetched before dispatch; table is a known workstream map, not a substitute for current PR state. PR status and review/CI can change.

## 2. Canonical in-repo owners to inspect before changing code

| Concern | Existing owners | Do not create |
|---|---|---|
| Market source catalog/discovery | \`src/market/source_catalog.py\`, \`src/resources/market_source_catalog.json\`, \`src/market/discovery.py\` | second source registry or arbitrary provider aliases |
| Source admission/campaign | \`src/qualification_campaign/sources.py\`, \`src/qualification_campaign/cli.py\`, \`profiles.py\`, \`transport.py\` | another campaign CLI or authorization boolean |
| Raw evidence/quotas/replay | \`src/qualification_campaign/evidence.py\`, AGG-02 owners and existing raw journal/cursor contracts | second journal or in-memory quota only |
| Rooted RPC | \`src/qualification_campaign/rpc.py\`, provider governance / governed transport owners | second RPC client/quorum implementation |
| Asset/mint identity | AssetResolver, DynamicUniverse, ResearchEconomicGraph registry, PR117 asset-mint registry | ticker resolver or duplicated token registry |
| Market facts/stream gap semantics | \`src/market/observations.py\`, \`src/market/streams.py\`, \`src/strategy/market_graph_ingest.py\` | second observation/watermark/stream buffer |
| Direct quote/route | #659 CPMM, #660 CLMM/DLMM, R13-K physical identity dedup, PR118 amount grid | second quote schema, route graph or size solver |
| Capital | \`src/lending/\`, \`src/providers/marginfi/\`, FlashCapitalGraph and R02 owners | TVL-derived capacity or pooled provider aliases |
| Unsigned construction / exact simulation | R03 provider builder, canonical compiler/firewall, R05 final simulation owner | generic transaction-builder bypass |
| Paper runtime | \`src/paper_shadow/composition.py\`, installed paper service, durable lifecycle, QPR/R06 owners | standalone while-loop/custom paper trader |
| Operation evidence | \`src/observability/events.py\`, \`src/observability/store.py\`, MarketEpisode, AGG-02 | duplicate event bus, NATS or duplicate datastore |
| Repo intelligence | existing \`src/intelligence\` / Local Intelligence V2, #666 W0B | second graph/index database without measured need |

The #680 audit found zero production \`make_event()\` callsites on its pinned main and default runtime metadata such as \`runtime_id="test-runtime"\` / \`producer_code_version="unknown"\`. Re-run this exact audit on latest main before coding. If still true, W10 producer wiring is real work, not documentation polish.

## 3. First-wave official source entry points

Use existing dated local dossiers and pins first; revalidate official contracts at implementation time. These links are entry points, not evidence that endpoints are currently supported, licensed for a given use, enabled or within quota.

| Source | Official entry point | What must be pinned/rechecked |
|---|---|---|
| DEX Screener | https://docs.dexscreener.com/api/reference | endpoint/path, schema, rate limits, terms, discovery-only role |
| GeckoTerminal / CoinGecko | https://docs.coingecko.com/reference/introduction | current network/pool endpoints, auth/quota, schema/terms |
| Raydium API V3 | https://api-v3.raydium.io/docs/ | current endpoints/schema and API role vs direct account state |
| Meteora | https://docs.meteora.ag/ | exact currently supported DLMM Data API path/schema; don't infer from docs root |
| Solana RPC | https://solana.com/docs/rpc | getMultipleAccounts/getSlot/getGenesisHash/getVersion, commitment/context/minContextSlot semantics |
| Jupiter Swap V2 | https://dev.jup.ag/docs/swap/v2/order | comparator only, auth/quota, request/response schema |
| 0x | https://0x.org/docs | Solana endpoint/OpenAPI, auth and fee semantics |
| Jupiter Lend | https://developers.jup.ag/docs/lend/flashloan | official flashloan semantics only; live state required for capacity |
| Project 0 | https://github.com/0dotxyz/p0-ts-sdk | exact SDK/IDL and deployed program/bank binding |
| Kamino | https://github.com/Kamino-Finance/klend-sdk | flash borrow vs standard obligation borrow; deployed state |
| NAVI (later Sui wave) | https://naviprotocol.gitbook.io/navi-protocol-developer-docs | package, coin type, checkpoint/object/hot-potato proof |

Also inspect current local packs:
- \`docs/roadmap/paper-data-campaign-universe-2026-11-21/\`
- \`docs/roadmap/campaign-start-preflight-2026-11-21/\`
- \`docs/roadmap/live-data-qualification-2026-11-21/\`
- \`docs/roadmap/clmm-dlmm-market-trace-qualification-2026-11-15/\`
- \`docs/roadmap/agent-execution-master-2026-11-13/\`
- \`docs/roadmap/intelligence-operating-plane-2026-11-21/\`

## 4. Exact source and evidence classification

Use independent fields for:
- contract/documentation state;
- credential configured state (reference name only; never value);
- request/read state;
- rooted/finalized state;
- complete dependent-state closure;
- exact quote state;
- route/resource independence;
- R02 capacity state;
- R03 builder state;
- R05 final simulation state;
- installed paper state.

Every row must have a retrieval timestamp, source/operator/correlation group, code/source generation and raw evidence reference where applicable. A vendor's marketing statement, API response or fixture cannot set a later field to PASS.

## 5. Known gaps that must remain visible unless newly disproved

- #679 says executable CS-01..10 and Windows fixes are not completed by this docs PR.
- #671 explicitly records no executable script implementing the entire CAMPAIGN_START gate at time of its handoff.
- #670 Windows receipt was not green: uvloop lock marker, Proactor pytest-socket fixture behavior, SQLite WinError 32. After fixing Proactor fixture, rerun and classify the genuine baseline failures.
- #680 observed zero production EventEnvelope producers; continuous runtime operation evidence is therefore unproven.
- #681 measured required-reference recall around 0.6667 at 500/1000/2000-token context budgets; W0B must improve using its own golden corpus/acceptance contract, not claim completion from benchmark creation.
- #682 reported no runtime observation plane and streaming source modes absent in its snapshot; static provider catalog is not a running data feed.
- Live data baseline says registry decimals are not enough; live owner/decimals/Token-2022 assertions must run before HARD_BOUND.
- #660 report's exact quote engines are offline/replay proven, not live differential proof. Rooted state still requires separately authorized two-source capture.
- Offline R02/R03 qualification is not live capacity. At least one resource must pass rooted evidence and its matching builder before the paper route.
