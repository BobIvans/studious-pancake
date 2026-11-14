# cetus_clmm_pool@2026-11-14 — Sui market wave-2 dossier (docs-only)

Wave-2 entry. ADDITIVE to: (a) `docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/SOURCE_LEDGER.json` `cetus` row (RESEARCH_SUI, "direct current deployment not inspected" — this wave closes exactly that gap at the docs level); (b) PR #621 `CETUS_AGGREGATOR_SUI.md` (aggregator SDK QUOTE routing — different surface, cited not duplicated). Status: `OFFLINE_BEHAVIOR_REFERENCE_ONLY` for routing/discovery; pool/lender capacity NOT claimed.

Fact classes: `RAW_OFFICIAL_SNAPSHOT` (Move struct fields + mainnet IDs copied verbatim from pinned official repos), `DOCS_REFERENCE_ONLY` (official docs behavior), typed blockers.

## Source pins (verified 2026-11-14)

- `CetusProtocol/cetus-clmm-interface` @ main `991f50e23dd0e34d134adb3b0ad4c1d30ab45e50` (committer date 2026-10-28T07:24:56Z, GitHub API). Contains the current CLMM Move sources.
  - `sui/cetus_clmm/sources/pool.move` (L39): verbatim pool schema:
    ```move
    struct Pool<phantom CoinTypeA, phantom CoinTypeB> has key, store {
        id: UID,
        coin_a: Balance<CoinTypeA>,
        coin_b: Balance<CoinTypeB>,
        /// The tick spacing
        tick_spacing: u32,
        /// The numerator of fee rate, the denominator is 1_000_000.
        fee_rate: u64,
        /// The liquidity of current tick index
        liquidity: u128,
        /// The current sqrt price
        current_sqrt_price: u128,
        /// The current tick index
        current_tick_index: I32,
        /// The global fee growth of coin a,b as Q64.64
        fee_growth_global_a: u128,
        fee_growth_global_b: u128,
        /// The amounts of coin a,b owned to protocol
        fee_protocol_coin_a: u64,
        fee_protocol_coin_b: u64,
        /// The tick manager
        tick_manager: TickManager,
        /// The rewarder manager
        rewarder_manager: RewarderManager,
        /// The position manager
        position_manager: PositionManager,
        /// is the pool pause
        is_pause: bool,
    ```
    (struct continues past L79 with remaining fields; the listed fields are the
    state-relevant ones transcribed this wave). Package name `cetusclmm`, Move.toml
    version `1.2.0`; dependencies referenced via MVR (`@cetuspackages/...`).
- `CetusProtocol/cetus-clmm-sui-sdk` @ main `bb37cda30d5aca63c2398e6886a1701cca1cf87d` (committer date 2025-02-28T10:23:03Z — **~9 months stale at retrieval; staleness typed below**). `src/config/mainnet.ts` verbatim mainnet IDs:
  - clmm pool package: `0x1eabed72c53feb3805120a081dc15963c204dc8d091542592abaf7a35689b2fb`
  - clmm `published_at`: `0xc6faf3703b0e8ba9ed06b7851134bbbe7565eb35ff823fd78432baa4cbeaa12e`
  - pools registry object (`pools_id`): `0xf699e7f2276f5c9a75944b37a0c5b5d9ddfd2471bf6242483b03ab2887d198d0`
  - `global_config_id`: `0xdaa46292632c3c4d8f31f23ea0f9b36a28ff3677e9684980e4438403a67a3d8f`
  - `global_vault_id`: `0xce7bceef26d3ad1f6d9b6f13a953f053e6ed3ca77907516481ce99ae8e588f2b`
  - cetus config package: `0x95b8d278b876cae22206131fb9724f701c9444515813042f54f0a426c9a3bc2f`
  - (also transcribed: `admin_cap_id`, `coin_list_id`, launchpad/clmm registry handles — full set in SOURCE_MANIFEST.json)
- Official docs: https://cetus-1.gitbook.io/cetus-developer-docs/developer/via-sdk/features-available/fee.md (fetched 2026-11-14): tick-spacing↔fee-rate table — 2→0.0001, 10→0.0005, 60→0.0025, 200→0.01; "Each tick spacing corresponds to a specific fee rate"; single-pathway fee = input × fee rate. SDK pool-query surface: `sdk.Pool.getPool(pool_id)` etc. (`getting-clmm-pools.md`, fetched 2026-11-14); sqrt price is X64 (`TickMath.sqrtPriceX64ToPrice`).

## Units / decimals semantics

- `fee_rate` is a **ratio numerator over 1_000_000** (struct doc comment) — decimal-independent. Example mapping: docs-table 0.0025 ↔ `fee_rate = 2500` in the u64 field (consistent with 1e6 denominator; the u64↔float mapping must still be re-confirmed per pool at read time).
- Coin decimals live in each `CoinTypeA/B` Move metadata (SUI=9 etc.) — the Pool struct carries none; never assume 9.
- `current_sqrt_price: u128` is sqrt-price-X64; `current_tick_index: I32` is the signed tick; balances are `Balance<CoinType>` u64 amounts in smallest units.

## Flash-loan status (negative finding, typed)

`MISSING_PIN` — no flash-loan entry point, hot-potato receipt, or lender fee was found
in the pinned `cetus_clmm` Move sources reviewed this wave (pool.move reviewed; the
historic NAVI-docs comparison of a "low-level Move flashloan" in the wave-1 ledger
row remains `SECONDARY_OFFICIAL_COMPARISON_ONLY`). Cetus CLMM is a SWAP/discovery
surface, not a pinned flash lender. Capacity: **UNKNOWN** (never zero; pool
`Balance` fields would be the eventual read surface, not gathered).

## Typed blockers

- `BLOCKED_MISSING_PIN`: on-chain live package/object ID confirmation (SDK config
  snapshot is 2025-02-28; Sui packages upgrade and `published_at` may drift — needs a
  governed R-02 bounded read or an official newer config source).
- `BLOCKED_MISSING_PIN`: live pool balances / liquidity depth (capacity) — R-02.
- `BLOCKED_MISSING_PIN`: per-pool fee_rate + pause state (state, not constant).
- `EXTERNAL_CONFORMANCE_MISSING`: PTB simulation proof (R-05-equivalent for Sui).
- Router/QUOTE overlap: PR #621 owns aggregator routing; this dossier owns pool
  schema/identity. Do not merge the two surfaces in one capability row.
