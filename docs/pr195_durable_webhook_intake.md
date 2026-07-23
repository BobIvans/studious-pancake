# PR-195 — Durable webhook intake slice

This PR starts the V3 PR-195 durable runtime-kernel package after the already
merged PR-195 control-plane and durable-lifecycle slices.

## Scope

`src/pr195_durable_webhook_intake.py` adds a sender-free SQLite/WAL inbox for
Helius-style webhook events. It establishes the acceptance boundary that legacy
HTTP handlers must later use before returning HTTP 2xx:

- validate the complete batch before writing any durable receipt;
- commit accepted events in one `BEGIN IMMEDIATE` transaction before ACK;
- keep immutable chain identity separate from mutable payload hashes;
- quarantine same-chain-identity payload drift instead of processing it twice;
- support owned claims, retryable nacks, dead-letter terminal state and expired
  claim recovery.

## Audit coverage

This slice targets the V3 PR-195 intake findings around ACK durability and
exactly-once semantics: lost worker failures, schema-before-ACK, atomic batch
receipt, shutdown/restart recovery and payload-hash identity drift.

## Safety boundary

No signer, private key, transaction construction, simulation, RPC/Jito
submission, provider calls, live mode or canary mode is added. This is an
offline durable-intake acceptance primitive only.

## Verification

```bash
python -m pytest -q tests/test_pr195_durable_webhook_intake.py \
  --disable-socket --allow-unix-socket
python -m compileall -q src/pr195_durable_webhook_intake.py \
  tests/test_pr195_durable_webhook_intake.py
```

Repository verification also includes the focused PR-195 webhook intake tests.
