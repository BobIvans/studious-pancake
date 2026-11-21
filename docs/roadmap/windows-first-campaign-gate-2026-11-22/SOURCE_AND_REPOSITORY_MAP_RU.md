# Карта кода и официальных источников для PR #679

Этот файл указывает агенту, где искать действующие owner contracts и каким источникам доверять. Ссылки являются отправными точками. Перед изменением кода заново проверь URL, дату, auth scope, ToS/license, schema/version и лимиты. Нельзя считать search snippet достаточным доказательством.

## 1. Внутренние owners — сначала читать их

| Задача | Canonical paths | Что переиспользовать |
|---|---|---|
| CAMPAIGN_START gates | docs/roadmap/prequal-rnd-2026-10-06/package/data/acceptance_gates.json; docs/roadmap/prequal-rnd-2026-10-06/package/04_CAMPAIGN_START_GATE_RU.md | CAMPAIGN_START_V1 CS-01..CS-10 |
| V2 preflight | docs/roadmap/campaign-start-preflight-2026-11-21/ | V2 manifest, policy bundle, profiles, operator checklist, source recheck |
| Previous campaign spec | docs/roadmap/paper-data-campaign-universe-2026-11-21/ | manifest V1, runbook, DAG, source crosswalk, readiness |
| Capture runtime | src/qualification_campaign/cli.py | current capture/replay entrypoint; no second runner |
| Campaign identity | src/qualification_campaign/identity.py | canonical_bytes, digest, CampaignManifest, clean checkout |
| Source profiles | src/qualification_campaign/profiles.py | ProviderProfile, READ_RPC_METHODS, provider entitlement |
| Source intake | src/qualification_campaign/sources.py | SourceDossier, CatalogDiscoveryAdapter, SourceIntakePlane |
| RPC | src/qualification_campaign/rpc.py; src/data_plane/rpc.py | NativeRootedSnapshotProvider, RootedRpcQuorumGate |
| Durable evidence | src/qualification_campaign/evidence.py; src/market/streams.py | CampaignEvidenceStore, attempt ledger, replay integrity |
| Provider budgets | src/provider_governance/authority.py; src/provider_governance/runtime.py; src/provider_governance/models.py | reviewed entitlements, physical attempts, quota pools, durable provider state |
| Market source IDs | src/market/source_catalog.py; src/market/discovery.py; src/resources/market_source_catalog.json | canonical source identity and actual DiscoveryRequest IDs |
| Current example config | config/qualification/representative-sources.json | starting shape only; existing docs TTL expired and only three entries |
| Release/runtime authority | src/runtime_authority.py; src/resources/runtime_authority.json; src/release_gate/ | existing canonical generation/release checks |
| Runtime verification | scripts/verify_repo.py; scripts/validate_authority_map.py | established verification commands |
| Lock regeneration | scripts/lock_requirements.py; pyproject.toml; requirements.lock | one source of dependency truth; never hand-edit generated lock |
| Windows test bootstrap | tests/conftest.py | Proactor/pytest-socket issue |
| SQLite/WinError 32 | scripts/verify_occ_durable_host.py; src/occ_durable_library.py | connection lifecycle and temporary cleanup |
| pmm-sim verifier | scripts/verify_pmm_sim_caller_profile.py; vendor/strategy-research/pmm-sim-cc4ae891/SHA256SUMS; research/pmm-sim-caller-profile/scenario_manifest_v1.json; caller_profile_results.csv | #665 failures; separate PR ownership |

## 2. Solana official RPC contracts

Use official Solana RPC documentation, not aggregator tutorials, to verify method parameters, response context and commitment semantics:

- General RPC reference: https://solana.com/docs/rpc
- getMultipleAccounts: https://solana.com/docs/rpc/http/getmultipleaccounts
- getSlot: https://solana.com/docs/rpc/http/getslot
- getGenesisHash: https://solana.com/docs/rpc/http/getgenesishash
- getVersion: https://solana.com/docs/rpc/http/getversion

Use exact methods actually called by src/qualification_campaign/rpc.py and its collectors. Keep the provider profile RPC allowlist and MPR2602 connection registry semantically aligned. Do not add getBlock or getBlockHeight merely because an old checklist mentions it; confirm actual implementation call sites and the schema enum first. A JSON-RPC read method is not proof of provider independence.

Quorum policy must use two independent provider companies/operators/correlation groups, same genesis, same requested accounts/state, finalized/rooted semantics, explicit context slots, bounded skew/freshness and state hashes. Two endpoints from one operator are not independent.

## 3. Official market-discovery source docs

These are discovery/indexed data sources, not rooted state or exact quotes. Agent must recheck current endpoint path and documented rate limit, save retrieval timestamp and SHA256, and preserve unknown terms/licensing as unknown.

- DexScreener API reference: https://docs.dexscreener.com/api/reference
  - Existing code endpoint: api.dexscreener.com/token-pairs/v1/solana/{mint}
  - Treat returned pair metadata as candidate discovery only.
- GeckoTerminal / CoinGecko API docs: https://docs.coingecko.com/reference/introduction
  - Previously pinned apiguide.geckoterminal.com URL redirected; update to current official docs and recheck public endpoint schema/limits.
  - Do not infer historical 30/min limit without current source confirmation.
- Raydium API V3 OpenAPI/Swagger: https://api-v3.raydium.io/docs/
  - Existing code uses /pools/info/list. Record the exact schema response envelope and pagination/limits.
- Meteora official docs root: https://docs.meteora.ag/
  - Find and pin the current DLMM Data API endpoint/schema from official documentation; do not use undocumented endpoints or assume the DLMM Data API is exact state.

Canonical adapter/source IDs currently visible in src/market/discovery.py include dexscreener, geckoterminal, raydium and meteora-dlmm. Resolve aliases explicitly against market_source_catalog.json; do not invent duplicate entries such as raydium_api_v3 vs raydium or meteora_dlmm_data vs meteora-dlmm without a registry contract and tests.

## 4. Jupiter and 0x — comparator-only future lane

These do not gate first discovery/rooted CAPTURE_ONLY. Keep credentials out of Git.

- Jupiter Swap V2 Order docs: https://dev.jup.ag/docs/swap/v2/order
- 0x API docs entry point: https://0x.org/docs

Verify the Solana-specific endpoint, authentication header, exact input/output units, quote/order/build semantics, terms, rate limits and whether data is comparator-only. Never conflate EVM V4 parameter changes with Solana schema. JUPITER_API_KEY and ZEROX_API_KEY values belong only in deployment-local secret management, never PR content or logs.

## 5. Windows and Python official references

- Windows 11 release health: https://learn.microsoft.com/en-us/windows/release-health/windows11-release-information
- Python 3.13 asyncio platform support: https://docs.python.org/3.13/library/asyncio-platforms.html
- Python 3.13 asyncio event loop: https://docs.python.org/3.13/library/asyncio-eventloop.html
- pytest-socket project contract: https://pypi.org/project/pytest-socket/
- uv compile documentation: https://docs.astral.sh/uv/pip/compile/
- SQLite Python connection lifecycle: https://docs.python.org/3/library/sqlite3.html

Windows 11 26H2 default asyncio loop is ProactorEventLoop. Never replace it with SelectorEventLoop just to make a test green without checking subprocess/pipe semantics. Python docs explicitly distinguish their Windows limitations. Do not globally allow outbound networking in tests to work around pytest-socket.

## 6. Upstream source/licensing rules

For every upstream code, IDL, binary, SDK, API schema or data snapshot:

1. Prefer vendor's official repository and documentation; record exact URL, commit/tag, blob SHA256, retrieval date, package version and license.
2. Check the license at the exact commit; package metadata or README badges are not enough.
3. If the source has no license, BSL/SSPL/custom/non-redistribution terms, do not vendor/redistribute source bytes unless repository policy and explicit licensing review permit it. Use commit/blob-hash provenance and a study-only citation where appropriate.
4. Do not use a tag as immutable identity if the tag does not point to the selected commit.
5. Record whether data is vendor docs, indexed snapshot, rooted capture, synthetic fixture or local simulation. These categories must never be merged.

Known project-specific licensing dispositions already recorded in the current lender work: fluid-solana-programs is BSL-1.1; jup-ag/jupiter-lend source was treated as no-license; these are study/provenance only, not an invitation to vendor them.

## 7. Evidence standards

A source is CURRENT only when the official docs URL was fetched, the exact API route/schema and date were recorded, terms/auth/quota were checked, and the pinned hash can be reproduced. DNS failure or redirect is an observation, not proof that a vendor disappeared. HTTP 429 is RATE_LIMITED, not a successful schema validation. A source with unknown licensing, cost, token semantics or deployment remains BLOCKED/UNKNOWN and cannot qualify an executable route.
