# MPR-NEXT-10 — Cryptographic submission boundary default-off

This file starts the dedicated review thread for **MPR-NEXT-10** from the fourth-pass production-readiness audit.

## Goal

Implement the missing upstream artifact for signer/submission boundary without opening live.

## Branch

`mpr-next-10-cryptographic-submission-boundary-default-off-v2`

The original `mpr-next-10-cryptographic-submission-boundary-default-off` branch name already existed, so this branch uses a `-v2` suffix to avoid overwriting parallel work.

## Scope captured from audit

- Add `src/release_gate/mpr30_cryptographic_submission_boundary.py` or an equivalent release-gate module.
- Bind transaction proof, semantic instruction firewall, signer reference, Jito policy, blockhash/ALT revalidation and finalized settlement intent.
- Keep the boundary **default-off**.
- Produce evidence kind: `cryptographic-submission-boundary`.
- Ensure MPR-31 can consume the MPR-30 artifact while still denying live runtime unless manual one-transaction canary conditions are met.

## Non-negotiable safety boundary

This PR must not:

- load a private key;
- enable signer IPC;
- submit a transaction;
- enable Jito submission;
- enable unrestricted live mode;
- claim paper-ready, shadow-qualified, live-ready or production-ready status.

## Intended acceptance commands

```bash
python -m compileall -q src scripts tests
PYTHONPATH=. python -m pytest -q tests/test_mpr30_cryptographic_submission_boundary.py tests/test_mpr31_final_promotion_gate.py
```

## First implementation slice target

The first code patch after this start document should create a **pure evidence contract** only:

1. a typed immutable evidence model for the default-off submission boundary;
2. validation that all required proof references exist and are digest-bound;
3. explicit denial when any live/signer/send/Jito capability is reachable;
4. MPR-31 compatibility without unlocking live;
5. focused negative tests for private key, sender, signer IPC and submit endpoint reachability.

## Review status

This is a start slice, not the full implementation.
