# PR-223 dispatch/finality recovery matrix gate

This document records the second safe slice for roadmap **PR-223 — Cryptographic
Trust, Isolated Signer, Submission and Finalized Settlement**.

The first roadmap PR-223 GitHub PR established the high-level offline trust and
settlement acceptance gate. This follow-up narrows the next review boundary to
the crash/recovery area that must be true before any isolated signer or live
canary cutover can be considered.

## Scope

The gate in `src/pr223_dispatch_finality_recovery_matrix.py` is deliberately
offline and side-effect free. It validates evidence for:

- accepted PR-219, PR-220, PR-222 and initial PR-223 gate prerequisites;
- exact PR-223 finding coverage;
- materialized non-placeholder signed immutable evidence;
- root-signed trust bundle, real Ed25519 verification, schema/domain separation
  and canonical serialization;
- authorization bound to config generation, release generation, wallet, plan,
  exact message digest, provider, market, reservation, session, nonce,
  not-before, expiry and selected transport;
- runtime inability to access or export private key material;
- signer-only signature and signed-wire production with local verification;
- one atomic permit -> intent -> outbox transition before transport;
- crash points across permit, intent, outbox, dispatch, receipt and
  reconciliation;
- no blind resend and no duplicate debit;
- Jito ACK, bundle ID and RPC signature remaining advisory until independently
  materialized finalized transaction evidence exists;
- finalized transaction evidence containing fee, balance, token balance, loaded
  address and program-log details;
- immutable archive receipts and append-only cross-plane reconciliation;
- dual approval, budget checks, rollback proof and default-disabled tiny canary.

## Safety boundary

This PR must not:

- load a private key;
- open signer IPC;
- sign bytes;
- build or submit transactions;
- call RPC, Jito, Jupiter, Helius, MarginFi or any provider;
- enable sender capability;
- enable live trading;
- enable default live canary.

A passing report only allows:

```text
dispatch_finality_review_allowed=true
signer_allowed=false
sender_allowed=false
live_execution_allowed=false
private_key_material_allowed=false
automatic_canary_allowed=false
unrestricted_live_allowed=false
```

## Relationship to roadmap PR-223

Roadmap PR-223 owns the path from accepted simulated payload to isolated signer,
durable dispatch and independently verified finalized settlement. This follow-up
does not implement that path physically. It makes the required next evidence
matrix executable and fail-closed before later commits touch signer, dispatch or
settlement runtime paths.

## Focused verification

```bash
PYTHONPATH=. python -m py_compile \
  src/pr223_dispatch_finality_recovery_matrix.py \
  tests/test_pr223_dispatch_finality_recovery_matrix.py

PYTHONPATH=. python -m pytest -q \
  tests/test_pr223_dispatch_finality_recovery_matrix.py
```

## Remaining physical work

Later PR-223 implementation slices still need to wire the contract into:

1. the real isolated signer process/package;
2. real Ed25519 verification and rotation/revocation stores;
3. durable permit, intent and outbox tables in the accepted control plane;
4. authenticated Jito/RPC transport evidence;
5. finalized `getTransaction` materialization and accounting deltas;
6. WORM archive backend verification;
7. governance for a tiny canary while keeping unrestricted live denied.
