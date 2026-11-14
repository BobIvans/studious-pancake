# deepbook_v3_flash@2026-11-14 — Sui market wave-2 dossier (docs-only)

Wave-2 entry. ADDITIVE to the wave-1 ledger row `deepbook` (P1_SUI,
`OFFICIAL_DOC`, facts `borrowBaseAsset`/`returnBaseAsset`/`borrowQuoteAsset`/
`returnQuoteAsset`, pinned to docs.sui.io flash-loans page — no repo pin). This wave
re-verifies the CURRENT official state (docs live 2026-11-14), adds the **Move-level
API** and the **official mainnet package ID from the published repo metadata**, and
corrects one number circulating in search snippets. Status: `OFFLINE_BEHAVIOR_REFERENCE_ONLY`;
flash capability is documentation-pinned but capacity is NOT claimed.

## Source pins (verified 2026-11-14)

- `MystenLabs/deepbookv3` @ main `3230fcd35a1bb74544115694e37a16f5f6842466` (repo
  pushed 2026-11-14T00:08:14Z — retrieved same day; license **Apache-2.0** via GitHub
  API; default branch `main`).
  - `packages/deepbook/Published.toml` (`RAW_OFFICIAL_SNAPSHOT`, verbatim):
    - `[published.mainnet] chain-id = "35834a8a"`,
      `published-at = "0xbca0cefe720330e7bb4f2283438b68de6a0e656688db4ac90d61e71fe6151fe8"`,
      `original-id = "0x2c8d603bc51326b8c13cef9dd07031a408a48dddb541963357661df5d3204809"`,
      `version = 9`, `toolchain-version = "1.82.2"`
    - `[published.testnet] published-at = "0x4b1c2a827983d8fa73f6dc366cfab23636ae52e81e499d8724b71408fe6a00a4"`,
      `original-id = "0xfb28c4cbc6865bd1c897d26aecbe1f8792d1509a20ffec692c800660cbec6982"`, `version = 21`
  - CORRECTION vs search-snippet noise: a web search snippet circulating a DeepBook
    mainnet package `0x2c8d552b...` does NOT match the official `Published.toml`
    (`0xbca0cef...` published / `0x2c8d603...` original). Snippets are not evidence;
    the repo metadata file is.
- Move API (`packages/deepbook/sources/pool.move` @ pinned SHA, verbatim signatures):
  ```move
  public fun borrow_flashloan_base<BaseAsset, QuoteAsset>(
      self: &mut Pool<BaseAsset, QuoteAsset>, base_amount: u64, ctx: &mut TxContext,
  ): (Coin<BaseAsset>, FlashLoan)
  public fun borrow_flashloan_quote<BaseAsset, QuoteAsset>(
      self: &mut Pool<BaseAsset, QuoteAsset>, quote_amount: u64, ctx: &mut TxContext,
  ): (Coin<QuoteAsset>, FlashLoan)
  public fun return_flashloan_base<BaseAsset, QuoteAsset>(
      self: &mut Pool<BaseAsset, QuoteAsset>, coin: Coin<BaseAsset>, flash_loan: FlashLoan)
  public fun return_flashloan_quote<BaseAsset, QuoteAsset>(
      self: &mut Pool<BaseAsset, QuoteAsset>, coin: Coin<QuoteAsset>, flash_loan: FlashLoan)
  ```
  `FlashLoan` is defined in the `vault` module (imported
  `vault::{Self, Vault, FlashLoan}` in pool.move L30); nat-spec: "FlashLoan object
  will only be unwrapped if the assets are returned". `packages/deepbook/sources/`
  contains no standalone `flash_loans.move` — the API lives in `pool.move` +
  `vault/`.
- Official docs (fetched 2026-11-14, both live):
  - https://docs.sui.io/onchain-finance/deepbook/deepbookv3-sdk/flash-loans — SDK
    wrappers `borrowBaseAsset(poolKey, borrowAmount)`,
    `returnBaseAsset(poolKey, borrowAmount, baseCoinInput, flashLoan)` (quote
    analogues likewise); "DeepBook charges nothing for a flash loan"; returning an
    amount != borrowed "aborts with `EIncorrectQuantityReturned`".
  - Flash-loan guide page confirms the hot-potato pattern: the borrow returns "a
    `FlashLoan` hot potato (struct with no abilities), which you must return to the
    pool by the end of the call"; if not repaid "The entire PTB reverts."

## Current flash-loan status (verdict)

**PINNED_CURRENT: flash loans are LIVE in the current official docs and source** (both
retrieved 2026-11-14; repo pushed 2026-11-14). Fee: docs state zero. This upgrades the
wave-1 `deepbook` row's evidence from docs-only to docs + pinned repo metadata; the
SDK-level function names in the wave-1 ledger row remain correct (SDK layer), now
joined by the Move-level names above.

## Capital vs discovery distinction (repo vocabulary)

- DeepBook flash loan is a **capital-edge candidate**: the hot-potato receipt is the
  Sui analogue of the EVM callback (see `SUI_PTB_ATOMICITY_WAVE2.md`). Lender capacity
  = the per-pool pool/vault balances of the *target pool* — state on shared objects,
  NOT derivable from docs. **Capacity: UNKNOWN** (a docs/repo pin is not capacity
  proof; no RPC/GraphQL/gRPC read was made).
- DeepBook's orderbook swap surface is a **discovery/quote** surface; do not double
  count pool liquidity as both quote depth and lender capacity without a correlation
  rule (the same shared object backs both; borrowing flash base/quote against a pool
  you also trade against must be modeled as one capital resource with one capacity).
- Shared-object contention: pool `Pool<BaseAsset,QuoteAsset>` is a shared object;
  concurrent orderbook traffic advances its version every checkpoint — a capacity
  read is only valid checkpoint-consistent (see R09 task language).

## Typed blockers

- `BLOCKED_MISSING_PIN`: live per-pool flash capacity (pool/vault balances) — R-02
  bounded read, never gathered. UNKNOWN, never zero.
- `BLOCKED_MISSING_PIN`: pool registry / `poolKey` enumeration pin (the SDK uses
  string poolKeys; official registry object mapping not pinned this wave).
- `BLOCKED_MISSING_PIN`: whether the zero flash fee is a constant or governance state
  (docs statement vs on-chain value).
- `EXTERNAL_CONFORMANCE_MISSING`: PTB simulation proof.
- License: Apache-2.0 (repo) — vendoring allowed with attribution; docs pages not
  vendored (editorial extracts only).
