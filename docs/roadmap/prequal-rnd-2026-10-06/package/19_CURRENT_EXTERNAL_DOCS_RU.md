# Current External Documentation Notes — checked 2026-10-06

## Project0 / marginfi
Official migration guide says `marginfi-client-v2` is deprecated and `@0dotxyz/p0-ts-sdk@^2.8.0` is the current minimum for program 0.1.11 oracle setups. This makes a fresh executable-conformance rebind mandatory.

## Pyth Core
Hermes authentication is mandatory after the 2026-08-26 upgrade. Official guide recommends upgraded `https://pyth.dourolabs.app/hermes` endpoint with `Authorization: Bearer $PYTH_API_KEY`; the old Hermes host also requires auth.

## Solana RPC
Official docs say public RPC is shared/rate-limited and not intended for production. Current docs list `https://api.mainnet.solana.com`; hardcoded older hostnames should be treated as replaceable source generations.

## Jupiter
Current pricing shows Free = $0, unlimited usage, 1 request/sec. Store plan generation; do not assume “unlimited” means unlimited RPS.

## OpenOcean
Current V4 quote docs require `amountDecimals` and `gasPriceDecimals`. Runtime/conformance request builders should be identical.

## DEX Screener
Official API reference: pair/search/token endpoints 300 requests/min; profile/boost-type endpoints 60/min. Excellent discovery source; not exact execution evidence.

## GeckoTerminal
Public API: no auth, 30 calls/min, beta. Pin version and use for discovery/reference only.

## Meteora DLMM
Official developer docs: indexed Data API 30 RPS. Useful for pool universe/metadata; exact DLMM execution still needs on-chain bins/dynamic fee evidence.

## Helius
Current pricing: Free includes 1M credits, 10 RPC RPS and standard WSS. Suitable as one provider/operator in a qualification data plane, not as two independent sources by multiplying endpoints.

Machine-readable URLs/facts: `data/current_verified_docs.json`.
