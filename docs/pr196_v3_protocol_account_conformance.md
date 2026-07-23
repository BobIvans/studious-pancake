# PR-196 V3 — Protocol/account conformance gate

This slice starts the revised V3 roadmap package:

**PR-196 — Bounded provider plane and protocol/account conformance**.

It is intentionally additive, offline and sender-free. It does not execute a
provider call, query RPC, build a transaction, import a signer, submit anything
or claim production readiness.

## Why this slice exists

The V3 audit moved the following acceptance boundaries into PR-196:

- canonical chain/program identity;
- Token-2022 program identity and default fail-closed extension policy;
- separate native SOL sentinel and wSOL SPL mint semantics;
- packaged or required-hash MarginFi/P0 provenance;
- rooted account, mint, oracle and ALT snapshots;
- bounded provider bodies, redirects, DNS resolution and retry/quota budgets;
- reviewed credentialed conformance fixtures and signed provider registry.

The gate added here turns those expectations into a deterministic typed report:

```text
pr196.protocol-account-conformance-v3.v1
```

## Files

- `src/pr196_protocol_account_conformance_v3.py`
- `tests/test_pr196_protocol_account_conformance_v3.py`
- `.github/workflows/pr196-protocol-account-conformance-v3.yml`

## Requirement map

| Requirement | Findings |
|---|---|
| `CANONICAL_CHAIN_PROGRAM_IDENTITY` | F-129, F-130 |
| `PACKAGED_MARGINFI_PROVENANCE` | F-139 |
| `ROOTED_ACCOUNT_MINT_ORACLE_ATTESTATION` | F-106…F-110, F-129 |
| `BOUNDED_PROVIDER_TRANSPORT_AND_QUOTA` | F-020…F-023, F-063, F-067 |
| `JUPITER_BUILD_ALT_BLOCKHASH_CONTRACT` | F-111…F-115 |
| `REVIEWED_CREDENTIALED_CONFORMANCE_FIXTURES` | F-116…F-123 |

## CI fix note

The first focused workflow run reached `py_compile` successfully and failed only
inside pytest. The focused tests now use `dataclasses.asdict()` rather than
`claim.__dict__`, because the claim dataclass is intentionally declared with
`slots=True` and therefore has no instance `__dict__`.

## Safety boundary

This slice always preserves:

```text
live_execution_allowed = false
signer_or_sender_allowed = false
```

The gate rejects any report invocation that tries to enable live execution or a
signer/sender surface in PR-196.

## What this does not complete

This is not the full PR-196 completion. Remaining work must wire the accepted
contract to:

- generated `ChainAddressRegistry` bindings;
- static scanner enforcement for forbidden duplicate program literals;
- packaged MarginFi/P0 provenance resources;
- current credentialed read-only fixtures;
- independently reviewed on-chain program/account vectors;
- provider registry signing and release-evidence packaging;
- active runtime gating after PR-194 and PR-195 are merged.

## Suggested focused verification

```bash
python -m py_compile \
  src/pr196_protocol_account_conformance_v3.py \
  tests/test_pr196_protocol_account_conformance_v3.py
python -m pytest -q tests/test_pr196_protocol_account_conformance_v3.py
```
