# PR-027 — External contract provenance

`src/resources/external_contracts.json` is the canonical machine-readable registry for every external API, protocol source, deployment id, schema and response artifact that may influence routing or execution.

## Safety contract

- Unknown fields are rejected.
- Official sources must use HTTPS and a provider-specific allowlisted host.
- Artifact paths must remain below `src/resources`.
- SHA-256 pins must be real 64-character hashes; all-zero placeholders are rejected.
- Missing or changed required artifacts produce `disabled-contract-drift`.
- Skipped online checks are never reported as verified.
- Credentials are read only for explicitly enabled conformance checks and are redacted from failures.
- Pin updates are review proposals; the updater never mutates the canonical registry.

## Current provider state

All API execution contracts remain `disabled-unverified`. This is intentional. PR-027 establishes provenance and fail-closed admission; it does not claim that Jupiter, OKX, Jito, OpenOcean or Odos response/instruction schemas are production verified.

MarginFi/Project Zero has two official source files pinned to upstream commit `d4c70c84f8a9692405a2c32cbd7095bb1fe3f428`, including the official mainnet program id. It remains disabled because the complete generated IDL, binary account layouts, deployed account golden bytes and instruction conformance belong to PR-028.

## Commands

```bash
flashloan-contracts validate
flashloan-contracts status
flashloan-contracts drift
flashloan-contracts conformance
flashloan-contracts conformance --enable-online
```

`conformance` without `--enable-online` returns `skipped-not-enabled` and `verified=false`.

To prepare a pin rotation for review without changing the registry:

```bash
flashloan-contracts propose \
  --contract marginfi.project-zero-mainnet \
  --artifact contracts/marginfi/flashloan.rs \
  --candidate /path/to/reviewed/flashloan.rs
```

The generated JSON must be reviewed together with semantic changes, offline tests, drift validation and any credentialed read-only conformance evidence before a canonical hash is rotated.
