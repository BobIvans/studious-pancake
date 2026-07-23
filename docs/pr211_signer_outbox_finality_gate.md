# PR-211 — Signer authorization, durable outbox and finalized settlement gate

This slice starts Pass 6 corrective **PR-211**.

The audit assigns PR-211 to signer authorization, durable outbox and finalized
settlement. This branch deliberately remains an offline acceptance gate: it does
not import private keys, Solana RPC clients, senders or live submission code.

## Scope

The new gate emits:

```text
pr211.signer-outbox-finality-gate.v1
```

It fails closed unless evidence proves:

- accepted PR-210 sender-free qualification evidence exists;
- signed payload authorization respects not-before, requested, signed-at,
  expiry and current-height safety-margin constraints;
- signature evidence is not a naked signature-set hash and was locally verified
  over exact message bytes with signer identities;
- canary/manual approval is threshold-signed and current, not hash-only;
- permit consumption, immutable intent creation and outbox row creation happen in
  one durable transaction;
- the dispatcher receives only an opaque immutable intent ID;
- response/finality reconciliation is idempotent and blind resend is impossible;
- crash before send and crash after send before ACK are reconciled;
- late landing freezes descendants;
- finalized settlement is materialized from `getTransaction`/meta/balance
  evidence, not caller-supplied hashes and booleans;
- intent, message, signature, transport and minContextSlot lineage are preserved;
- landed transactions charge authoritative fee from transaction meta.

## Findings covered

- F-249 — signed payload after authorization expiry;
- F-250 — signature-set hash is not cryptographic verification;
- F-251 — hash-only canary approval;
- F-252 — failed landed transaction with zero charged fee;
- F-253 — caller-supplied hashes/booleans as finality evidence;
- F-254 — minContextSlot not bound to intent/blockhash/simulation context;
- F-255 — permit, intent and transport side effect need one durable outbox protocol.

## Safety boundary

This PR does **not** enable:

- live trading;
- signer/private-key loading;
- transaction construction;
- RPC/Jito submission;
- provider calls;
- production DB migration;
- real finalized settlement queries.

A clean report still returns:

```text
live_execution_allowed = false
signer_import_allowed = false
sender_import_allowed = false
```

## Suggested verification

```bash
python -m py_compile \
  src/pr211_signer_outbox_finality_gate.py \
  tests/test_pr211_signer_outbox_finality_gate.py
python -m pytest -q tests/test_pr211_signer_outbox_finality_gate.py
```

## Remaining implementation after this gate

The full PR-211 implementation must wire these invariants into the post-PR-210
installed runtime with real signer IPC, Ed25519 verification over exact message
bytes, atomic permit/intent/outbox storage, bounded dispatcher recovery and
rooted finalized `getTransaction` reconciliation. Live remains compile-time and
deployment-policy blocked until PR-212 promotion evidence is accepted.
