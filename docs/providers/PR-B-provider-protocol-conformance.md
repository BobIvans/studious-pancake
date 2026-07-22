# MEGA-PR B — Provider/protocol conformance first slice

This PR starts **MEGA-PR B — Credentialed provider conformance, rooted
protocol evidence and reliable ingestion**.

It is not a full provider integration and it does not enable live trading. The
purpose of this slice is to create an executable, package-visible conformance
contract that MEGA-PR A can use before admitting any external adapter into the
sender-free paper vertical.

## Runtime-facing contract

`src.providers.protocol_conformance` defines:

- bounded provider/protocol evidence entries;
- provider, purpose, auth-mode and promotion-state enums;
- official reference metadata with review date;
- request/response schema hashes;
- credentialed probe and negative fixture hashes;
- timeout, retry, quota and freshness contracts;
- drift revocation requirements;
- a report that returns deterministic blockers.

The module is exported from `src.providers`, so wheel/source package parity can
include it without importing excluded `src.ingest` legacy code.

## Provider safety rules covered now

- Jupiter route build must use current Swap V2 `/swap/v2/build`.
- Legacy Jupiter `/swap/v1/*`, `/swap/v2/quote` and `/swap/v2/swap-instructions`
  shapes are not promotable.
- Jito tip-account discovery must be JSON-RPC `getTipAccounts`, not a REST
  `tip_accounts` path.
- Helius delivery evidence must use an Authorization-header contract.
- MarginFi fee/repayment truth cannot be an environment percentage.
- Kamino unsupported-combination registries must remain blocked until real
  supported-combination evidence exists.
- Provider drift must revoke admission.

## Non-goals

- No network probing from CI.
- No credential storage.
- No sender, signer, Jito submission or RPC mutation.
- No packaging of the historical `src.ingest` tree.
- No claim that protected provider probes have already been executed.

## Verification

```bash
python -m pytest tests/test_pr_b_provider_protocol_conformance.py -q
python scripts/verify_repo.py
```

MEGA-PR A should treat this contract as an admission preflight for provider
fixtures and external adapters before any captured candidate is processed.
