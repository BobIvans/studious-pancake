# SOURCE_MATRIX — official contracts and bounded integration order (checked 2026-10-07)

**These are onboarding targets, not live-authorized runtime entries.** Check actual provider entitlement, rate-limit headers, ToS, endpoint schema, protocol/SDK pins and availability again during coding. Published numerical ceilings apply only to the named endpoint and tier; not a blanket allowance for all calls, accounts, operators or IPs. The previous GPR/UXE R&D matrices are historical source evidence.

## Layer 1: broad discovery and market inventory

| Provider | Chain | API / official documentation | Known cap or access | Earliest integration / what to trust |
| --- | --- | --- | --- | --- |
| DEX Screener | Solana, Sui, multi | https://docs.dexscreener.com/api/reference | Pair/token routes **300 RPM**; promotional profile routes **60 RPM**; token multi-address endpoint batches up to **30** | **DIN-01 P0**. Batch minted-token universe, pool identity and liquidity. Indexer **not** on-chain exact proof |
| GeckoTerminal | Multi | https://apiguide.geckoterminal.com/faq | Public **30 calls/min** | **DIN-01 P0**. Cross-indexer pool discovery, never independent operator proof for same underlying AMM |
| Raydium API v3 | Solana | https://api-v3.raydium.io/docs/ | No contract-wide cap reverified; probe conservatively | **DIN-01 P0**. CPMM/CLMM source inventory; verify exact pool program and binary layout |
| Meteora DLMM | Solana | https://docs.meteora.ag/api-reference/dlmm/overview | Old GPR pack cites **30 RPS**; **unconfirmed current entitlement** | **DIN-01 P0**. Venue discovery; confirm DLMM account state via chain when shortlisted |
| Manifest | Solana | https://github.com/Bonasa-Tech/manifest | Endpoint/book limits **not confirmed** | **DIN-01 P1**. CLOB market/book research. Known large ticker response needs bounded node/byte caps |
| Orca Whirlpools | Solana | https://dev.orca.so/ | Not verified; SDK/chain-dependent | **DIN-01 P1**. Add venue-specific market/fee math only after program/version pin |
| Sanctum | Solana | https://learn.sanctum.so/docs/for-developers/sanctum-api | Not verified | **DIN-05**. LST registry, withdrawal exit/NAV structural facts; label conversion delay/atomicity |
| DeepBook V3 | Sui | https://github.com/MystenLabs/ts-sdks/tree/main/packages/deepbook-v3 | SDK/source specific; not assumed unlimited | **DIN-02 P0**. Known pool registry, book depths, lot/fee, checkpoint proof |
| Cetus | Sui | https://cetus-1.gitbook.io/cetus-developer-docs/ | Not verified | **DIN-02 P0**. Indexer pool context, direct quote then exact pool state |
| Aftermath | Sui | https://docs.aftermath.finance/ | Prior pack cites router **1000/10s**, not revalidated | **DIN-02 P0**. Targeted router data; retain oversized-response negatives |
| Scallop | Sui | https://docs.scallop.io/ | Not verified | **DIN-02 P1**. Rates, supported assets, lender fee research |
| NAVI | Sui | https://sdk.naviprotocol.io/ | Not verified | **DIN-05**. Lending/flash capacity + fee with live read |
| Sui gRPC / GraphQL | Sui | https://docs.sui.io/develop/accessing-data/ | **Per provider**, separate accounts/operators not default independent | **DIN-02 exact**. Checkpoint/object state. **Do not use Foundation Mainnet JSON-RPC** (disabled July 2026) |

## Layer 2: quote and unsigned builder race

| Provider | Chain | Official docs | Free/baseline access evidence | Correlation/implementation warning |
| --- | --- | --- | --- | --- |
| Jupiter | Solana | https://developers.jup.ag/docs/portal/rate-limits | **Free 1 RPS** general; keyless **0.5 RPS**, org-wide sliding limit; separate execute/submit buckets **not permission to broadcast** | **DIN-03**. Reference route/quote. Use `api.jup.ag` and scoped `x-api-key`; avoid stale `quote-api.jup.ag` |
| 0x Solana | Solana | https://docs.0x.org/svm/solana-swap-api/guides/get-started-with-solana-swap-api | Open beta; API key required. Earlier GPR docs suggested ~5 RPS, **current exact tier not reverified** | **DIN-03**. Instructions + ALTs; normalize route, amount, taker and fee; NEVER transmit signer |
| Titan | Solana | https://developer.titan.exchange/ | **Sandbox $0, 1 RPS, 2.5M credits/month** (developer portal) | **DIN-03**. Alternative router. Separate API provider does not always imply disjoint underlying liquidity |
| OpenOcean Solana | Solana | https://docs.openocean.finance/docs/solana-swap-api | **Default 2 RPS**; **Solana API key and allowlist** required, even where public general docs discuss open access | **DIN-03 P1**. Aggregates **Jupiter + Titan**; tag as correlated meta-route, not a third independent liquidity proof |
| OKX OnchainOS DEX | Solana/Sui | https://web3.okx.com/onchainos/dev-docs | Developer credential/tier; current numeric cap not reverified | **DIN-03 P2**. Quote/transaction builder; entitlement/fee and correlation profiling first |
| Rango | Solana/Sui/TON | https://docs.rango.exchange/api-integration/api-key-and-rate-limits | Key / contractual tier; unknown default numerical cap | **DIN-03 P2**. Multichain route and unsigned transaction; **not** local cross-chain atomicity |
| Aftermath Router | Sui | https://docs.aftermath.finance/for-developers/typescript-sdk/products/router | SDK / service-specific; rate unknown now | **DIN-04 P0**. Can append route to PTB; source assets and sub-provider lineage |
| Cetus Aggregator | Sui | https://cetus-1.gitbook.io/cetus-developer-docs/developer/cetus-aggregator/getting-started | API/SDK per tier | **DIN-04 P0**. PTB route; full pool coin type and shared coin objects |
| DeepBook direct | Sui | https://github.com/MystenLabs/ts-sdks/tree/main/packages/deepbook-v3 | Direct chain/provider read cost | **DIN-04 P0**. Direct CLOB path; lot/tick/fees, not an indexer executable assumption |
| 7K / Bluefin7K | Sui | https://7k.ag/ | SDK endpoint and limits require refreshed review | **DIN-04 P1**. Aggregator of other providers; old JSON-RPC fallback risk in dependent integrations |
| FlowX | Sui | https://flowx.finance/ | Current developer endpoint docs must be re-pinned | **DIN-04 P1**. Correlated meta-router; verify supported providers and unsigned PTB |
| OKX / Rango Sui | Sui | official docs above | Tier-dependent | **DIN-04 P2**. Only after provider identity and gRPC/GraphQL state support pinned |

## Layer 3: reference/oracle, trigger and capital

| Source | Scope | Official source | Authentication / boundary |
| --- | --- | --- | --- |
| Pyth Core / Hermes | Solana + Sui oracle research | https://docs.pyth.network/price-feeds/core/upgrade/preparing | Since **2026-08-26, Bearer API key required**; PR #566 governs `FLASHLOAN_PYTH_API_KEY_REFERENCE`. Oracle reference ≠ exact swap pricing |
| Switchboard | Oracle/reference | https://docs.switchboard.xyz/ | Reviewed feed IDs, slots, signer/consumer settings, per-tier |
| Helius | Solana stream/webhook/RPC | https://www.helius.dev/docs | Free tier/quotas and allowed endpoints must be read from own plan. Webhook/WS trigger only; reconnection/gap replays |
| Birdeye | Market context | https://docs.birdeye.so/ | Key/credits required; no invented free unlimited quota |
| Vybe | Solana parsed data | https://docs.vybenetwork.com/ | Key/credits as configured; prior GPR cap is historical |
| CEX public WS (Coinbase/Kraken/Binance/Bybit) | Cross-venue price/lead-lag | Individual official API docs | Public book context may be fee-free, but rate/connection/ToS constraints; never same-chain atomic executor proof |
| Project 0 | Solana flash loan/capital | https://github.com/0dotxyz/p0-ts-sdk and https://github.com/0dotxyz/marginfi-v2/blob/main/guides/USER/FEES.md | Official docs describe **no protocol flashloan fee**. Live bank operational state, borrow cap, tag and liquidity mandatory; don't assume deposit-only banks lend |
| Kamino KLend | Solana flash capital | https://github.com/Kamino-Finance/klend-sdk | Reserve/protocol limits and fees read live; explicit borrow/repay exact instruction pair |
| NAVI / DeepBook / Scallop | Sui flash capital | docs above | Loanability/capacity/fees per coin/pool/protocol; normalize to base units, do not assume 0 fee |
| Slumlord | Solana ephemeral rent financing | https://github.com/igneous-labs/slumlord | Only after builder, all rent-funded accounts closed and loan repaid in same tx; **rent is not swap capital** |
| STON/Omniston/DeDust/TonAPI | TON research only | https://docs.ston.fi/developer-section/dex/api/reference / https://docs.ton.org/ | Optional deferred; no Solana-style all-or-nothing multi-contract assumption |

### Explicit exclusions / hazards

- **Odos retired** from runtime source registry by main PR #566. Historical fixtures may be replayed but do not re-enable Odos as a Solana quote/routing source by default.
- Public `api.mainnet-beta.solana.com` or one provider under two hostnames is **not** independently verified rooted quorum. Operator independence requires reviewed distinct providers and context agreement.
- Sui Foundation Mainnet JSON-RPC was **disabled in July 2026**, with removal expected October 2026. A vendor SDK that secretly falls back to JSON-RPC fails closed.
- Free/fair-use: **no daily/monthly cap ≠ unlimited RPS**. Measure physical successful/admitted calls and respect provider headers/entitlements.
- The 0x and Jupiter quotes can yield routes with different intermediate venues; normalize and fingerprint provider lineage before comparing.

## Onboarding recipe, one source at a time

1. Pin the official source URL, relevant endpoint docs, SDK commit/release, time checked, method/path/query schema and hash.
2. Capture approved host/proxy/TLS, key reference, operator identity, provider correlation family, per-key/per-org/per-IP limit, shared dependent quota and daily/credit budget.
3. Add `SourceDossier`, `ProviderProfile` and a bounded adapter; back it with immutable positive/negative fixtures, schema-drift/oversize/429/401 replay.
4. Prove no wire call without `ProviderGovernance` admission; record response hash, version/time/slot/checkpoint, exact source/chain/representation identity.
5. One real low-budget smoke probe with reviewed credential. Report accepted/blocked physical calls and HTTP status; do not promote to exact graph.
6. Integrate into Dynamic Universe → ResearchEconomicGraph → VerificationQueue only after contract tests. Separate exact verification and paper qualification remain blocking.

See `PROVIDER_CATALOG.json` for machine-readable priority, auth and correlation tags. **Catalog is a proposed onboarding queue, not a runnable provider config.**
