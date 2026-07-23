# PR-199 — Isolated signer, exactly-once submission and finalized canary gate

This document tracks the seven-PR roadmap meaning of **PR-199** from the pass-3 production-readiness audit.

The PR-199 boundary is the first place where a minimal live-capable path may exist, but only after accepted PR-198 sender-free evidence. This slice does not implement live transport. It adds an offline acceptance gate for the evidence that must exist before signer/submission code can be considered reviewable.

## Scope

The gate validates evidence for:

- accepted PR-198 sender-free qualification evidence;
- physically isolated signer process/service;
- no private key bytes or signer backend import in the general runtime;
- signer request digest binding attempt, generation, message, config, wallet, provider, market, reservation, nonce and expiry;
- local signature verification and signed-payload hash binding;
- atomic permit + reservation + submission-intent consumption;
- durable submission intent before the first network byte;
- no blind retry policy;
- immediate blockheight validity recheck before sign/send;
- canonical recovery through `getSignatureStatuses(searchTransactionHistory=true)` and `getTransaction(finalized)`;
- Jito bundle id or ACK never becoming success;
- landed failed transaction fee accounting from finalized transaction metadata;
- one-in-flight limited canary with wallet allowlist, per-attempt/day loss ceilings and emergency latch.

## Safety boundary

This PR does **not** enable:

- live trading;
- signer/private-key access;
- signer backend imports;
- RPC or Jito submission;
- transaction construction;
- simulation;
- automatic retry;
- canary mode;
- production DB migration.

A clean report still returns:

```text
live_capability_allowed = false
signer_backend_allowed = false
sender_transport_allowed = false
```

## Verification

```bash
python -m py_compile \
  src/pr199_live_boundary_canary_gate.py \
  tests/test_pr199_live_boundary_canary_gate.py
python -m pytest -q tests/test_pr199_live_boundary_canary_gate.py
```

## Remaining full PR-199 work

This gate is not the full implementation. Later slices must wire it into the accepted PR-198 evidence bundle, canonical PR-195 lifecycle authority, real isolated signer IPC/HSM/KMS, transport-specific RPC/Jito adapters, finalized settlement accounting, operator runbooks and real canary budget artifacts before any live activation can be reviewed.
