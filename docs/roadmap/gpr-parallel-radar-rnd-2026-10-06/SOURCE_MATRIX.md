# Source matrix — checked 2026-10-06

All numerical limits below are source-documented where stated. `recommended campaign cap` values are our deliberately lower engineering defaults, not provider promises.

| Source | Chain | Role | Documented free/public limit | Initial campaign cap | Phase |
|---|---|---|---|---|---|
| dexscreener | multi | RADAR_INDEXER | 300 requests/minute on pair/token endpoints | 240 requests/minute maximum; prefer batch reads | EXISTING_QPR03 |
| meteora-dlmm | solana-mainnet | HIGH_THROUGHPUT_RADAR | 30 RPS | 24 RPS initial cap | IMPLEMENT_NEXT |
| 0x-solana | solana-mainnet | QUOTE_PREVIEW_B | approximately 5 RPS Free/Standard tier across endpoints | 4 RPS initial cap | IMPLEMENT_NEXT |
| jupiter | solana-mainnet | QUOTE_PREVIEW_A_FINAL | Free: unlimited usage, 1 request/second general API limit; separate execute/submit buckets exist | 1 request every 1.25 seconds for read-only qualification | IMPLEMENT_NEXT |
| sanctum | solana-mainnet | STRUCTURAL_LST_QUOTE | numeric public rate limit not established in checked docs; 429 is documented | 0.5 RPS until observed limits are characterized | IMPLEMENT_NEXT_SPECIALIZED |
| openocean-solana | solana-mainnet | QUOTE_PREVIEW_C | 2 RPS default public plan / Solana API | 1.5 RPS | OPTIONAL_NEXT |
| okx-dex | multi | QUOTE_COMPARATOR | Trial 1 RPS default, up to 5 RPS after review; 60 days | 0.8 RPS | OPTIONAL_TRIAL |
| geckoterminal | multi | RADAR_INDEXER | 30 calls/minute public API | 24 calls/minute | EXISTING_QPR03 |
| raydium | solana-mainnet | VENUE_INDEXER | no stable numerical public limit pinned by this R&D review | retain current QPR-03 conservative bounded profile until measured | EXISTING_QPR03 |
| vybe | solana-mainnet | PARSED_REFERENCE | Free: 60 RPM, 25,000 credits/month | 48 RPM plus credit budget | IMPLEMENT_LATER_OR_PARALLEL |
| birdeye | multi | SPARSE_REFERENCE | Standard/free: 1 RPS, 30,000 compute units | 0.5 RPS and strict CU budget | BACKLOG |
| aftermath | sui-mainnet | SUI_HIGH_THROUGHPUT_ROUTER_RADAR | 1000 requests / 10 seconds default (100 RPS) | 80 RPS initial cap with per-method subcaps | IMPLEMENT_PARALLEL_AFTER_SHARED_GRAPH |
| cetus | sui-mainnet | SUI_DIRECT_VENUE_STATE | not pinned numerically in checked official docs | 1 RPS until measured and documented | IMPLEMENT_PARALLEL_AFTER_SHARED_GRAPH |
| sui-grpc-graphql | sui-mainnet | SUI_EXACT_STATE_TRANSPORT | provider-specific; no invented global rate | profile-specific, fail closed | IMPLEMENT_PARALLEL_AFTER_SHARED_GRAPH |
| stonfi | ton-mainnet | TON_UNLIMITED_RESEARCH_RADAR | Currently no rate limits for the DEX API | self-imposed 20 RPS initially; adaptive lower on errors | IMPLEMENT_RESEARCH_ONLY_AFTER_SHARED_GRAPH |

## Official links
- **dexscreener**: https://docs.dexscreener.com/api/reference
- **meteora-dlmm**: https://github.com/MeteoraAg/docs/blob/main/developer-guides/dlmm/api-reference/overview.mdx
- **0x-solana**: https://docs.0x.org/docs/developer-resources/rate-limits
  - secondary_docs: https://docs.0x.org/svm/solana-swap-api/introduction
- **jupiter**: https://developers.jup.ag/pricing
- **sanctum**: https://learn.sanctum.so/docs/for-developers/sanctum-api
- **openocean-solana**: https://docs.openocean.finance/docs/solana-swap-api
  - pricing_docs: https://docs.openocean.finance/docs/swap-api/api-pricing-and-access
- **okx-dex**: https://web3.okx.com/onchainos/dev-docs/trade/api-fee
- **geckoterminal**: https://apiguide.geckoterminal.com/faq
- **raydium**: https://docs.raydium.io/raydium/build/resources/apis
- **vybe**: https://docs.vybenetwork.com/docs/plans-rate-limits
- **birdeye**: https://docs.birdeye.so/docs/pricing
- **aftermath**: https://docs.aftermath.finance/for-developers/api/rest-api/authorization
  - router_docs: https://docs.aftermath.finance/trade/smart-order-router
- **cetus**: https://cetus-1.gitbook.io/cetus-developer-docs/developer/via-sdk-v2/getting-started
  - pool_list_docs: https://cetus-1.gitbook.io/cetus-developer-docs/developer/via-sdk/features-available/smart-router-v2
- **sui-grpc-graphql**: https://docs.sui.io/develop/accessing-data/
  - migration_docs: https://docs.sui.io/references/sui-sdks
- **stonfi**: https://docs.ston.fi/developer-section/dex/api/reference
