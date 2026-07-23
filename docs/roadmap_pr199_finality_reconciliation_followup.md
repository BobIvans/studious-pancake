# PR-199 follow-up: signer IPC, finalized reconciliation and canary gate

This is a second, additive PR-199 slice.  The earlier PR-199 scaffold created
the fail-closed permit, authorization digest and exactly-once submission-intent
boundary.  This follow-up keeps live submission disabled, but adds the missing
evidence contracts that must exist before a real signer process or sender can be
wired.

## Scope

- `PR199SignerIsolationEvidence` proves the signer is a separate policy service:
  the runtime does not hold private keys, signer egress is restricted, wallet
  files and env-private-key schemes are rejected, and a policy hash is bound to
  every signer session.
- `PR199SignerRequestEnvelope` hashes the exact authorization request, permit,
  signer-isolation evidence, caller identity and block-height request point.
- `PR199SignedPayloadBinding` verifies that the signer response matches the
  durable intent, exact message hash, signed payload hash and current signer
  identity before any sender handoff is allowed.
- `PR199FinalizedChainEvidence` makes finality depend on both
  `getSignatureStatuses(searchTransactionHistory=true)`-style evidence and a
  finalized `getTransaction` record, not on a transport ACK or Jito bundle id.
- `reconcile_finalized_attempt()` moves ACK/UNCERTAIN attempts to FINALIZED only
  after finalized chain evidence, and carries charged fee plus settled native
  delta into a reconciliation report.
- `PR199OperatorCanaryGate` requires zero outstanding/UNKNOWN attempts,
  non-expired manual approval and a cleared emergency latch before the first
  bounded canary can even be considered.

## Safety boundary

This PR still does **not** add or enable:

- private-key loading;
- signer IPC implementation;
- HSM/KMS integration;
- transaction signing;
- Jito/RPC submission;
- automatic retry;
- live/canary activation;
- ACK or bundle-id based settlement.

`COMPILE_TIME_LIVE_SUBMISSION_ENABLED` remains `False`, and the follow-up status
payload reports that no live transport implementation is present.

## Focused verification

```bash
PYTHONPATH=isolated_signer_service/src \
python -m pytest -q tests/test_pr199_finality_reconciliation_followup.py

python -m compileall -q \
  isolated_signer_service/src/flashloan_isolated_signer \
  tests/test_pr199_finality_reconciliation_followup.py
```

## Remaining full PR-199 work

This is still not the full live boundary.  Later slices must connect the
contracts here to the accepted PR-198 evidence bundle, the canonical PR-195
lifecycle authority, real isolated signer IPC/HSM/KMS, transport-specific
Jito/RPC send adapters, finalized-chain accounting, operator runbooks and a
strict canary budget before any live use.
