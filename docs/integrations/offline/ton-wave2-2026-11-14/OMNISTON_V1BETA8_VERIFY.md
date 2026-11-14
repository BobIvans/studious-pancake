# Omniston RFQ — wave-2 re-verification of the wave-1 v1beta8 pin

**Retrieved:** 2026-11-14 UTC
**Verification URLs:** https://docs.ston.fi/llms.txt (docs index), https://docs.ston.fi/developer-section/omniston/swap/v1beta8 (API model page), https://docs.ston.fi/developer-section/omniston/environments (environments page)
**Result: `PINNED_CURRENT`** — the wave-1 pin (`stonfi.omni.v1beta8`) is still the current API namespace; nothing in the radar changes.

## What wave-2 verified (all verbatim from official docs)

1. **Namespace currency:** the API model page still titles itself "API model v1beta8" and states the namespace `stonfi.omni.v1beta8` "is the current API namespace".
2. **Docs index status:** `docs.ston.fi/llms.txt` lists "WebSocket API v1beta8", "gRPC API v1beta8" and "API model v1beta8" as the current Omniston pages; v1beta7 appears only under `developer-section/omniston/migration/` as "Legacy WebSocket API v1beta7" / "Legacy gRPC API v1beta7", plus a "API v1beta7 to v1beta8" migration guide. No v1beta9/v1 stable page exists in the index.
3. **Environments unchanged vs wave-1:** production `wss://omni-ws.ston.fi` and `omni-grpc.ston.fi:443`; sandbox `wss://omni-ws-sandbox.ston.fi` and `omni-grpc-sandbox.ston.fi:443`.
4. **Settlement branches:** the API model page confirms the RFQ -> Quote -> swap-or-order flow and `quote.settlementData.$case` (`swap` or `order`) branch selection described in the wave-1 dossier.

## New wave-2 observations (no action taken)

- The docs index now lists official **Omniston SDK pages** ("TypeScript/JavaScript (Node.js)" and "React hooks"). The SDK package/version was **not** captured this wave: typed `MISSING_PIN` for the Omniston SDK version. The radar keeps its injected `OmnistonReader` protocol and never imports any Omniston SDK, so no radar code depends on this pin.
- The versioning page reference ("Versions and migrations", "current support status and migration paths") confirms upstream treats the namespace as versioned and migratable; the radar's decode contract is namespace-agnostic (route records only), so a future v1beta9/v1 migration touches only the injected reader's owner.

## Radar consequence

- `OmnistonReader` (injected read-only route reader, `normalize_ston_payload("routes", ...)`) stays exactly as in wave 1. The route record contract remains: bounded underlying pool identities (1..5 unique pool addresses per route), single-pool routes share the pool's `correlation_group`, records stay `DISCOVERY_ONLY`.
- No socket transport, no quote subscription, no `TonRpc.BuildSwap` / `BuildEscrowTransfer` / order lifecycle methods — unchanged boundary from wave 1.
