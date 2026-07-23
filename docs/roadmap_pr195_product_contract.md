# Roadmap PR-195 — Product contract, typed configuration and secret identity

## Scope

This change starts numeric roadmap PR-195 as a fail-closed product-contract
foundation. It does not enable mainnet, live, signer or sender capability.

The PR binds the existing typed runtime configuration and capability matrix to a
single PR-195 contract hash covering:

- runtime mode semantics;
- provider endpoint origins and REST/RPC paths;
- raw-secret environment aliases that must not be used for product evidence;
- redacted configuration evidence;
- capability graph consistency for the supported entrypoint.

## Implemented

- Adds `config/product_contract_pr195.json` and packaged
  `src/resources/product_contract_pr195.json`.
- Adds `src/config/product_contract_pr195.py` with offline validation for:
  - runtime schema binding;
  - live hard-deny consistency;
  - endpoint origin drift;
  - capability/default-mode contradictions;
  - raw legacy secret aliases such as `OKX_PASSPHRASE`.
- Updates the capability matrix so active runtime/runner components honestly
  allow the default sender-free shadow mode while live remains unavailable.
- Updates `.env.example` to use `*_REFERENCE` secret references and origin-only
  endpoint variables instead of raw API-key/passphrase examples.
- Adds regression tests for the PR-195 product contract, secret alias rejection
  and default-mode capability graph validation.

## Deliberately absent

- No provider credential resolution is performed by the product-contract check.
- No external endpoint is contacted.
- No Helius/Jupiter/OKX/Jito adapter is promoted.
- No live, signer, sender, canary or settlement path is enabled.

Later PRs must wire this contract hash into release manifests, continuous
runtime evidence, provider drift probes and canary approval.
