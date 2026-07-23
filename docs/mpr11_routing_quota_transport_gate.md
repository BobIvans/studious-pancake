# MPR-11 — Routing quota, freshness and transport conformance gate

This slice starts the V6 **MPR-11** package for provider quota, request identity, quote freshness and transport conformance.

It is an offline acceptance gate. It does not call Jupiter, OpenOcean, Odos, OKX, Solana RPC, Jito, Helius, MarginFi or Kamino. It does not construct, simulate, sign or submit transactions.

## Covered V6 findings

This gate covers the V6 MPR-11 finding range F-304…F-313 as a fail-closed materialized-evidence contract:

- F-304/F-305: canonical typed cache identity, descriptor verification, bounds and generation awareness.
- F-306: idempotent quota state transition and account-wide reservation authority.
- F-307/F-308: finite/causal scheduler timing, atomic plan reservation and profile-failure non-resurrection.
- F-309: canonical Solana public-key decoding and normalization instead of regex-only validation.
- F-310: no-expiry quote execution rejection, trusted time/slot freshness and chain/provider validity binding.
- F-311: actual-client transport policy attestation and rejection of insecure injected clients.
- F-312: request/response risk binding for Jupiter slippage and swap mode.
- F-313: adapter echo binding and route identity from program/pool/account/blockhash evidence rather than labels.

## Safety boundary

A passing `MPR11GateReport` always returns:

```text
live_execution_allowed=false
provider_network_allowed=false
signer_allowed=false
```

The gate only validates already-materialized evidence. It is not the runtime cutover and it does not make old provider adapters production-ready.

## Focused verification

```bash
python -m compileall -q \
  src/mpr11_routing_quota_transport_gate.py \
  tests/test_mpr11_routing_quota_transport_gate.py
python -m pytest -q tests/test_mpr11_routing_quota_transport_gate.py
```

## Remaining full MPR-11 work

Later slices must wire this contract into the actual Jupiter/OpenOcean/Odos/OKX adapters, quota store, cache, scheduler, quote admission and transport factory. The installed artifact must then prove all V6 adversarial probes fail closed against the real runtime surface.
