# External contract provenance

`src/resources/external_contracts.json` is the canonical machine-readable registry for every external API, protocol source, deployment id, schema and response artifact that may influence routing or execution.

## Safety contract

- Unknown fields are rejected.
- Official sources must use HTTPS and a provider-specific allowlisted host.
- Artifact paths must remain below `src/resources`.
- SHA-256 pins must be real 64-character hashes; all-zero placeholders are rejected.
- Missing or changed required artifacts produce `disabled-contract-drift`.
- Skipped online checks are never reported as verified.
- Credentials never promote a disabled or discovery-only contract.

## Current provider state after PR-030

- Jupiter Swap V2 build: `active` for quote plus composable-instruction discovery.
- OKX, OpenOcean and Odos: `discovery-only`.
- Jito and live submission: `disabled-unverified`.
- MarginFi remains governed by its separate binary/IDL/RPC and runtime release gates.

Jupiter being composable does **not** make live execution available. Exact planning, simulation, reconciliation, permit and live gates remain separate requirements.

## Commands

```bash
flashloan-contracts validate
flashloan-contracts status
flashloan-contracts drift
flashloan-contracts conformance
flashloan-contracts conformance --enable-online
```
