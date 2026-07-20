# PR-063 — Canonical Jito/RPC sender consolidation

## Goal

PR-063 turns the merged PR-045 sender implementation into one supported
composition boundary. It does not enable live trading. The only supported new
entry point is `CanonicalPermitBoundSender`, configured for exactly one
transport and backed by the existing one-use permit issuer.

The roadmap requirement is: permit-bound submission only, current RPC/Jito
contracts, explicit Jito credential modes, bounded status polling, exactly one
tip, durable ambiguity, and no automatic duplicate submission.

## Canonical API

```python
config = CanonicalSenderConfig(
    transport=TransportKind.JITO_SINGLE,
    rpc_endpoint="https://rpc.example",
    jito_base_url="https://mainnet.block-engine.jito.wtf",
)
sender = CanonicalPermitBoundSender(config, http_transport)
await sender.submit(permit, signed_payload, message_hash)
```

`RpcSender` and `JitoSender` remain available as explicit compatibility imports
for the merged PR-045 tests and downstream migrations, but they are no longer
advertised through `src.submission.__all__`. New runtime composition must use
the canonical facade.

## One transport, no fallback

A `CanonicalSenderConfig` selects exactly one of:

- Solana RPC `sendTransaction`;
- Jito single transaction;
- Jito bundle.

The resulting `LiveSubmissionPolicy` allowlists only that transport. A permit
for another transport is rejected before a network call. The facade never
falls back from Jito to RPC or from RPC to Jito and never fans one signed
payload out to multiple senders.

## Jito credential modes

The current Jito default send path no longer requires an approved auth key.
PR-063 therefore distinguishes two explicit modes:

- `default`: no `x-jito-auth` header is emitted;
- `uuid`: a parsed UUID is required and is emitted only as `x-jito-auth`.

Supplying a UUID while selecting default mode fails closed. Selecting UUID mode
without a UUID also fails closed. Credentials are never embedded in endpoint
URLs or diagnostics.

## Status and ambiguity

The facade always polls Solana `getSignatureStatuses` as the authoritative
on-chain status source. For a Jito acknowledgement carrying a bundle ID it also
queries `getInflightBundleStatuses` and `getBundleStatuses`.

Jito evidence can strengthen diagnostics but cannot overrule missing or
conflicting Solana signature evidence. A Jito `Landed` status with a missing
signature remains `unknown`. Conflicting landed/failed evidence also remains
`unknown`.

Every `CanonicalStatusReport` sets `automatic_resubmit_allowed=false`.
Accepted, unknown, failed, or expired outcomes must pass through the durable
PR-041/045 lifecycle and require an explicit new permit/rebuild decision. No
status result directly triggers another submission.

## Tip invariant

The canonical facade reuses PR-045's payload-bound tip evidence. Jito submission
still requires exactly one approved System Program transfer across the complete
payload. The tip account must come from current `getTipAccounts` evidence and
must be a static account, not an address lookup table entry.

## Current official contract references

- Solana `sendTransaction` and `getSignatureStatuses`.
- Jito `/api/v1/transactions`, `/api/v1/bundles`,
  `/api/v1/getInflightBundleStatuses`, `/api/v1/getBundleStatuses`, and
  `/api/v1/getTipAccounts`.
- Jito default sends do not require an approved auth key; UUID remains an
  explicit credential mode.
- Jito bundles contain one to five signed transactions; status requests accept
  at most five bundle IDs; the documented minimum tip is 1000 lamports.

The sanitized contract metadata is stored in
`tests/fixtures/pr063/official_sender_contract.json`.

## Safety and parallel work

This patch is isolated to `src/submission`, a new focused test, a fixture, and
this document. It does not modify active runner composition, capital
reservations, discovery, planner/compiler/simulation/reconciliation, signer,
canary, external-contract registry, or release-gate files. Live remains
compile-time and configuration default-deny.

## Verification

```bash
python -m pytest tests/test_pr045_permit_bound_submission.py \
  tests/test_pr063_canonical_sender.py -q --disable-socket --allow-unix-socket
python -m black --check src/submission tests/test_pr063_canonical_sender.py
python -m mypy --config-file mypy.ini src/submission
python -m compileall -q src/submission tests/test_pr063_canonical_sender.py
python scripts/verify_repo.py
```
