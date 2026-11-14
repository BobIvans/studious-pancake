# Omniston API v1beta8 — contract extract (read-only RFQ path)

**Retrieved:** 2026-11-14 UTC
**Canonical URLs:** https://docs.ston.fi/developer-section/omniston/swap, .../swap/overview, .../swap/v1beta8, .../environments, .../how-omniston-works
**API namespace:** `stonfi.omni.v1beta8` (current per official docs). JSON-RPC 2.0 over WebSocket; snake_case on the wire (SDK exposes camelCase). gRPC over TLS also offered.
**Environments (verbatim):** production `wss://omni-ws.ston.fi`; sandbox `wss://omni-ws-sandbox.ston.fi`; history `wss://omni-history-ws.ston.fi`, `https://omni-history.ston.fi/json-rpc`, `omni-history-grpc.ston.fi:443`; trading gRPC `omni-grpc.ston.fi:443` (prod), `omni-grpc-sandbox.ston.fi:443`.
**Auth:** none documented on captured pages. **Published limits:** none captured.

## Verified read-only quote path (the only part in radar scope)

- Method: `stonfi.omni.v1beta8.QuoteRpc.Quote` (no method literally named `requestQuote` in the current API).
- Request (verbatim example from official docs):
  ```json
  {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "stonfi.omni.v1beta8.QuoteRpc.Quote",
    "params": {
      "input_asset": { "ton": { "native": {} } },
      "output_asset": { "ton": { "jetton": "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs" } },
      "input_units": "1000000000",
      "settlement_params": [ { "swap": { "max_price_slippage_pips": 10000 } } ]
    }
  }
  ```
- Response: `{"jsonrpc":"2.0","id":1,"result":17}` — result is a numeric subscription id.
- Notifications use the same method name with `"params": {"subscription": 17, "result": {...}}`; event variants: `ack` (`{"ack": {"rfq_id": "..."}}`), `quote_updated` ("carries the executable Quote"), `no_quote`, `keep_alive`.
- Quote object: `quote_id`, `settlementData.$case` (`swap` or `order`), `input_units` (input paid by trader), `output_units` (trader's net output), `integrator_fee_units`, `protocol_fee_units`, `integrator_fee_pips`, `protocol_fee_pips` (one pip = `1/1,000,000`). Quotes expire; "check the selected quote's deadline before committing."
- Unsubscribe: `<method>.unsubscribe` with `"params":[<subscription id>]`. Reconnect: "re-open required subscriptions and use the new IDs"; do not auto-resubmit accepted operations.

## Out-of-radar methods (recorded to make the boundary explicit)

`TonRpc.BuildSwap`, `TonRpc.BuildEscrowTransfer`, `EvmRpc.BuildOrderPayload`, `OrderRpc.RegisterSignedOrder`, `SwapRpc.Track`, `OrderRpc.Track`, `OrderRpc.GetActive`, `OrderRpc.DiscloseHtlcSecret`, plus all order/settlement lifecycle flows. The repository owner never invokes these; there is no socket transport in `src/discovery/dynamic_universe/ton_radar.py`.

## Adapter seam

The radar keeps Omniston as the injected `OmnistonReader` protocol (`discover_routes(markets, *, max_routes)` returning read-only `{routes: [{pool_addresses, input_asset, output_asset}]}`). The injected implementation owns the real wire contract; the radar only decodes route records, requires bounded underlying pool identities (1..5 unique pool addresses per route), and tags single-pool routes with the pool's correlation group. Route/quote records remain `DISCOVERY_ONLY` and are never promoted to an exact graph.
