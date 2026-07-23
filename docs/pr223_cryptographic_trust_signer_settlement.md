# PR-223 — Cryptographic trust, isolated signer, submission and finalized settlement

## Status

This branch starts the roadmap **PR-223** as a safe additive slice.
It does **not** enable signer access, sender I/O, RPC/Jito transport or live
trading. The implementation is an offline acceptance contract that defines what
must be proven before the repository can claim a trustworthy path from accepted
PR-222 payload bytes to isolated signing, durable dispatch and finalized
settlement.

## Why this slice exists

The roadmap assigns PR-223 ownership over the cryptographic boundary between:

- root-signed trust material;
- exact authorization envelopes;
- isolated signer custody;
- atomic permit → intent → outbox dispatch;
- transport identity binding;
- authoritative finalized settlement;
- immutable archive/WORM receipt evidence;
- dual-approval promotion and canary governance.

Today, several historical layers still allow boolean/hash-style self-attestation.
This slice makes those requirements explicit and testable without activating any
side effect.

## Added files

- `src/pr223_cryptographic_trust_settlement_gate.py`
- `tests/test_pr223_cryptographic_trust_settlement_gate.py`
- `docs/pr223_cryptographic_trust_signer_settlement.md`
- `.github/workflows/pr223-cryptographic-trust.yml`

## What the gate requires

The evaluator blocks unless evidence proves all of the following:

1. **Trust root is real**
   - canonical serialization;
   - schema/domain separation;
   - real Ed25519 verification;
   - key rotation and revocation support;
   - not-before enforcement.

2. **Authorization is exact**
   - exact message digest binding;
   - wallet/release/provider/market binding;
   - durable nonce consumption;
   - valid issued/not-before/expiry window.

3. **Dispatch is exactly-once**
   - permit consumption and intent creation are linked;
   - durable outbox write is part of the same logical atomic boundary;
   - `DISPATCHED` is recorded before transport handoff;
   - provider idempotency and UNKNOWN reconciliation ownership exist.

4. **Transport does not claim settlement**
   - payload digest, minContextSlot and blockhash are bound;
   - RPC ACK is not treated as landing;
   - Jito bundle ID is not treated as landing.

5. **Settlement is authoritative**
   - finalized `getTransaction` is required;
   - finalized identity must match intent;
   - fee, balances and token deltas are materialized.

6. **Archive evidence is immutable**
   - WORM-like receipt;
   - published bytes are re-hashed;
   - receipt revision cannot be silently rewritten.

7. **Promotion remains governed**
   - at least two distinct independent approvals;
   - fresh trusted evaluation time;
   - aggregate budget verification;
   - rollback proof bound to the same release/evidence set.

## Safety boundary

A passing report still returns:

```text
signer_allowed=false
sender_allowed=false
live_execution_allowed=false
```

So this branch is a foundation slice, not an activation slice.

## Relationship to the mega-roadmap

This branch covers the first safe checkpoint of roadmap PR-223 from the uploaded
mega-roadmap file: root of trust, signed authorization, exactly-once dispatch,
transport/finality distinction, archive immutability and promotion governance.
The later PR-223 checkpoints must wire these invariants into the real isolated
signer service, real transport adapters and real finalized reconciliation.

## Focused verification

```bash
python -m py_compile \
  src/pr223_cryptographic_trust_settlement_gate.py \
  tests/test_pr223_cryptographic_trust_settlement_gate.py
python -m pytest -q tests/test_pr223_cryptographic_trust_settlement_gate.py
```

## Not included yet

This slice intentionally does not:

- load or export private keys;
- start a signer process;
- open RPC or Jito connections;
- submit transactions;
- release capital;
- book realized PnL;
- promote canary or live execution.
