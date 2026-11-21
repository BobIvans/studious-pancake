# Bounded read-only capture runbook — prepared, NOT activated

Status: PREPARED_ONLY. Nothing in this document has been executed. No credential value
is requested, stored or probed; only environment-variable NAMES appear. Activation
requires explicit human authorization as a separate PR/operation (assignment §8).

## Preconditions (all mandatory, each independently gated)

1. Operator-approved RPC profiles for at least two independently operated Solana RPC
   sources with different provenance/correlation groups:
   `SOLANA_RPC_URL_PRIMARY`, `SOLANA_RPC_URL_SECONDARY` (names only; values come from
   the approved deployment config, never from chat, fixtures or logs).
2. Governed transport profile with per-source quotas, timeouts and Retry-After policy
   (existing `src/provider_governance/` + `src/routing/transport.py` owners; no new
   transport).
3. Aggregator keys, if the comparison stage is authorized at all:
   `JUPITER_API_KEY`, `ZEROX_API_KEY` (confirm the canonical name accepted by the
   existing P0-2 owner before introducing any alias). Keyless Jupiter low-rate mode
   must be revalidated against current docs.
4. Replay workspace with the pinned code revision; no outbound network during replay.
5. Write paths: raw request/response retention with hashes; fixture vs live evidence
   separation is enforced by the existing evidence owners.

## Stage 1 — bounded pair-universe discovery (single bounded read)

- Seeds: SOL/USDC as the discovery seed hint only; candidates come from current pool
  metadata, never from a ticker assumption.
- Sources: DEX Screener `GET /latest/dex/search`, Raydium API V3
  `GET /pools/info/mint`, Meteora DLMM Data API pool listing — through the existing
  PR #561 discovery adapters with their bounded page/timeout limits.
- Record: raw request fingerprint + response hash, endpoint, generation, retrieval time.
- Output: candidate pool list with exact program IDs and pool addresses. Discovery
  metadata is never executable depth.

## Stage 2 — canonical identity resolution

- Resolve every candidate pool to canonical mint identity (mainnet genesis +
  mint + token program + decimals + extensions) via the existing AssetResolver owner.
- Reject symbol-to-mint inference; reject Token-2022 mints with unresolvable
  extensions (transfer hook → typed rejection; unknown extension tag → rejection).
- Record per-pool: venue family, fee/config revision, token program flags, decimals.

## Stage 3 — direct exact-state snapshot (rooted, two-source)

- One `getMultipleAccounts` per account group, ≤100 addresses per request; groups:
  - CLMM pool group: PoolState, AmmConfig, DynamicFeeConfig (when required),
    TickArrayBitmapExtension (when required), ordered reachable TickArrayState set,
    mints, vaults, observation/clock dependencies.
  - DLMM pool group: LbPair, BinArrayBitmapExtension (when required), active +
    directional BinArray set, clock/epoch, mints, reserves, Token-2022 mints.
  - Jupiter Lend group (only if the financing stage is authorized): admin state,
    TokenReserve, vault token accounts.
- Each response's `context.slot` is recorded per source. Multiple requests → multiple
  contexts; enforce `minContextSlot` and the bounded-skew policy, or reject/retry under
  governance. Never synthesize one common slot across responses.
- Compare at least two independent RPC providers; both must be fresh and coherent.
- Optionally use existing Helius stream modules as a change trigger only; rooted
  snapshots remain the quote evidence.

## Stage 4 — direct amount-specific quote grids (offline computation)

- Feed decoded account sets into `clmm_exact_in_quote` (with
  `bitmap_extension`/`dynamic_fee_config`/`block_timestamp` when required) and
  `dlmm_swap_exact_in_quote` (with `bin_array_bitmap_extension`, `clock_epoch`,
  `current_timestamp`, Token-2022 evidence when required).
- Amount grid via `build_pr118_amount_grid`; no extrapolation between points.
- Every quote records: amount in/out raw units, all fee fields by denomination, ticks
  crossed / bins used, arrays used, final price/liquidity, dynamic-fee or volatility
  provenance, consumed input, source slot/generation, raw account hashes, decoder/quote
  revisions, typed rejection reasons.
- Aggregator comparison (only if stage preconditions authorize it): Jupiter V2
  `GET /swap/v2/order` and 0x `POST /solana/swap-instructions` at the same canonical
  mint pair, same raw amount, bounded timestamp skew. Returned 0x instructions are inert
  evidence; never sign or submit. De-duplicate aggregator routes by physical pool
  identity (R13-K); opaque lineage marks resource independence UNKNOWN.

## Stage 5 — canonical observation and route qualification

- Feed only verified complete quotes into the existing canonical path:
  MarketObservationV2 → graph ingest → #659 route binding (now with the CLMM/DLMM
  qualified adapters) → R13-K dedup → PR118 per-size evaluation → economics.
- Produce trace rows for every candidate including no-trade/rejection; preserve raw
  request/response and account hashes; report stage denominators separately and split
  fixture vs live at every stage.

## Stage 6 — Jupiter Lend capacity read (only if authorized)

- Read TokenReserve/vault/admin/flashloan_fee state under the same rooted RPC rules.
- Run the existing `observe_token_reserve_capacity` →
  `admit_reserve_financing_snapshot` → `reserve_capital_edge_gate` chain verbatim.
- Never hardcode fee=0 from docs; capacity is UNKNOWN until rooted state proves it.
- R03 unsigned borrow → route → repay plan assembly stays unsigned; R05 exact
  simulation and R06 paper remain blocked behind their existing gates.

## Stage 7 — replay

- Re-run `scripts/clmm_dlmm_market_trace_replay.py`-class replays from retained
  evidence with zero outbound network; verify digest stability.

## Stop conditions and hard prohibitions

- Any account/ATA creation, signing, sending, borrowing, spending, deployment, provider
  activation, live mode or production promotion: STOP.
- Any credential value observed in logs/fixtures/reports: STOP and rotate via the
  operator; never commit or transmit it.
- Unknown fee state, unresolved transfer hooks, missing arrays/bins, stale or mixed
  generations: typed rejection, never a quote through.
