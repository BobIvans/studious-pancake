# MPR-02 — provider/protocol conformance and rooted data-plane gate

This checkpoint starts **MPR-02** from the four-MPR production-ready pack.

It is a sender-free, offline acceptance contract. It does not call Solana RPC,
Jupiter, Helius, MarginFi, Kamino, OKX, OpenOcean or Odos; it does not load
secrets; it does not construct, sign or submit transactions; it does not enable
live trading.

## Scope

The gate covers the required MPR-02 provider/protocol debts:

- `data.rpc-rooted-quorum`
- `data.oracle-slot-coherence`
- `external.solana-v0-rpc`
- `external.jupiter-swap-v2`
- `external.helius-webhook-auth`
- `external.marginfi-v2`
- `external.kamino-klend`
- `lending.kamino-supported-combinations`
- `external.okx-signed-discovery`
- `external.openocean-whitelist-discovery`
- `external.odos-immutable-transaction`
- `evidence.provider-drift-probes`

## Required checks

- Solana v0 RPC fixtures must bind exact message simulation, fee, blockhash
  lifetime, ALT provenance, versioned transaction lookup and finalized
  balance/token evidence to rooted quorum observations.
- Jupiter V2 `/build` must be the only execution-composable Jupiter path; V1
  execution claims must be disabled.
- MarginFi is either `fixture_only_blocked` or fully `conformance_ready` with
  IDL/layout, program/group identity, SDK vectors, read-only RPC evidence,
  flashloan borrow/repay metas, Token-2022 handling and human review.
- Kamino is either `disabled_fail_closed` or backed by reviewed
  market/reserve/asset provenance. Guessed IDs are rejected.
- Helius ingress requires auth, replay/dedup, gap recovery, durable handoff,
  rate/backpressure and recorded-vs-credentialed lineage.
- OKX/OpenOcean/Odos remain discovery-only unless separately proven
  flashloan-composable; Odos immutable transaction output stays incompatible
  with the initial flashloan composition path.
- Drift probes validate committed redacted fixtures in CI and permit only manual
  credentialed refresh that cannot commit secrets.

## Added files

- `src/mpr02_provider_protocol_data_plane_gate.py`
- `tests/test_mpr02_provider_protocol_data_plane_gate.py`
- `docs/mpr02_provider_protocol_data_plane_gate.md`

## Focused verification

```bash
PYTHONPATH=. python -m py_compile \
  src/mpr02_provider_protocol_data_plane_gate.py \
  tests/test_mpr02_provider_protocol_data_plane_gate.py

PYTHONPATH=. python -m pytest -q \
  tests/test_mpr02_provider_protocol_data_plane_gate.py
```

## Safety boundary

A passing report permits only review of provider/protocol evidence:

```text
provider_protocol_review_allowed=true
operational_paper_ready_allowed=false
live_execution_allowed=false
sender_allowed=false
```

The real MPR-02 completion still requires wiring this contract into
`docs/external_contracts.yaml`, `src/external_contracts/`,
`src/resources/contracts/`, provider adapters, data-plane admission and drift
refresh scripts with materialized redacted evidence.
