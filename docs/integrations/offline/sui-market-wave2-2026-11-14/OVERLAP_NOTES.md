# Sui market wave-2 — overlap notes vs prior lanes

Wave: 2026-11-14 (R09-L2 lane, docs-only). Branch `agent/evm-sui-dossiers-wave2`.

## What prior waves own (cite, never re-pin)

- `docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/SOURCE_LEDGER.json` +
  `SUI_PROTOCOL_DOSSIERS.md`: NAVI (P0), DeepBook (P1, docs-only flash-loan facts),
  Scallop (P1), Bucket (P2), Cetus (RESEARCH, secondary-only), Suilend. This wave
  upgrades the Cetus row (direct pool schema + mainnet IDs now pinned) and the
  DeepBook row (Move API + published package ID pinned; docs re-verified live) —
  both as additive wave-2 files; the ledger file itself is NOT edited by this PR.
- `docs/integrations/offline/providers-wave1-2026-11-13/` (PR #621):
  `AFTERMATH_SUI.md`, `CETUS_AGGREGATOR_SUI.md`, `FLOWX_SUI.md`,
  `SEVENK_BLUEFIN7K_SUI.md` own the **QUOTE routing** surfaces (SDK endpoints, fee
  fields, auth, error codes). This wave owns the **on-chain** surfaces (pool/package
  pins, Move schemas, flash-lender verdicts). A source may appear in both bundles
  with different fact classes — that is intentional, not duplication; each file
  cites its sibling.
- NAVI flash-loan PTB surface (`sdk.naviprotocol.io/lending/flashloan`,
  `getAllFlashLoanAssets`/`flashloanPTB`/`repayFlashLoanPTB`) is already ledger-pinned
  and owned by the P0 lane — not re-pinned here; NAVI is capital-side, handled by
  R02-CAP-C.

## Overlap/correlation rules for this wave

1. Aggregator SDK routes (#621) vs on-chain pools (this wave): a route computed via
   Cetus Aggregator SDK traverses CLMM pools pinned here — the pool schema/package
   pins here are the identity layer for those routes; keep both evidence classes
   separate (`QUOTE_ROUTING` vs `RAW_OFFICIAL_SNAPSHOT`).
2. DeepBook: one shared object backs orderbook depth AND flash-lender capacity —
   single capital resource, one capacity number (see DEEPBOOK_V3_FLASH_WAVE2).
3. Aftermath perps/DCA/limit-order packages are out of swap scope; never merge into
   swap routing rows.
4. Cetus has NO pinned flash lender (negative finding typed MISSING_PIN); NAVI and
   DeepBook are the only Sui sources with pinned flash mechanics as of this wave
   (Scallop/Bucket remain docs-pinned lender candidates per the ledger).
5. Code ownership: `src/multichain/sui.py` is the canonical Sui PTB/hot-potato model;
   `src/resources/multichain_capabilities.json` rows (`sui-mainnet:deepbook`,
   `sui-mainnet:cetus`, ...) stay `implemented_offline` with
   `PACKAGE_NOT_PINNED`/`INTERFACE_NOT_PINNED` blockers — note: this wave's pins
   address the *documentation* side of those blockers; the JSON would only be
   promoted (by its owner) after deployment + capacity proof. This PR does NOT edit
   the JSON.

## Cross-lane boundaries

- EVM wave-2 (same PR): `docs/integrations/offline/evm-financing-wave2-2026-11-14/` —
  no Sui facts copied there, no EVM facts copied here (domain isolation).
- ton-wave1 lane: untouched.
