# DEPRECATED — ASSET PLACEHOLDERS V1

This placeholders-only registry has been superseded by:

- `ASSET_REGISTRY_V2.json`

Do not delete this file yet because older GPR V1 material may reference it.

## New rule

The renewed R&D contains canonical research identities where the supplied research established them, but **every identity remains runtime-disabled and exact-graph-disabled by default**.

Do not convert the old placeholders into ticker-based aliases.

Use the status gates in `ASSET_REGISTRY_V2.json`:

- `RND_VERIFIED_CURRENT`
- `RND_VERIFIED_SPECIFIC_REPRESENTATION`
- `REVALIDATE_CURRENT`
- `REVALIDATE_ISSUER_STATUS`
- `UNRESOLVED`

Particularly:
- tBTC must be revalidated;
- sUSDS remains unresolved;
- Sui AUSD needs issuer-status revalidation;
- native and bridge/wrapped versions of USDC/USDT/BTC/SOL are distinct representations.
