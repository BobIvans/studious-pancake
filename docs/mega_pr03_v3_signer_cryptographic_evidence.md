# MEGA-PR-03 V3 — signer cryptographic evidence gate

## Purpose

This checkpoint extends the already-merged MEGA-PR-03 live-canary foundation with the V3 audit finding `IMPL-39`.

The defect is that the isolated signer prepare path can treat a caller-supplied `signed_wire_sha256` as evidence. That is not a cryptographic signature proof.

## Safety boundary

This PR is side-effect-free. It does not load a private key, open signer IPC, sign or verify real bytes, build or submit a transaction, call RPC/Jito/providers, enable sender IO or enable live execution.

The report always returns:

```text
live_execution_allowed=false
sender_allowed=false
unrestricted_live_allowed=false
automatic_scale_up_allowed=false
```

## Required signer behavior represented by this gate

A future live-canary cutover must prove that the isolated signer itself:

1. accepts exact reviewed message bytes;
2. reparses programs, accounts, amounts and fees;
3. binds the parsed message to MEGA-PR-02 paper-qualified evidence;
4. loads the key only inside the signer boundary;
5. produces the signature itself;
6. builds the signed wire itself;
7. verifies public-key/signature/message binding locally;
8. persists cryptographic evidence before one-time dispatch;
9. consumes a fenced dispatch token exactly once;
10. rejects duplicate dispatch, crash replay and caller-supplied signature/wire digests.

## Focused verification

```bash
PYTHONPATH=. python -m py_compile \
  src/live_boundary/mega_pr03_v3_signer_cryptographic_evidence.py \
  tests/test_mega_pr03_v3_signer_cryptographic_evidence.py

PYTHONPATH=. python -m pytest -q \
  tests/test_mega_pr03_v3_signer_cryptographic_evidence.py
```

Expected focused result:

```text
10 passed
```

## Remaining full MEGA-PR-03 work

This gate does not replace the real signer implementation. The remaining cutover must still wire an actual signer backend, durable IPC/auth, v0 finalized reconciliation, hard canary latches, one-in-flight live authorization, signed post-run evidence and independent go/no-go review.
