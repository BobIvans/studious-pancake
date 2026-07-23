# MPR-CLOSE-05 — Isolated signer, Jito semantics and bounded canary latches

This slice implements the MPR-CLOSE-05 boundary as a default-off, offline-verifiable foundation. It does not enable unrestricted live trading and does not let runtime code read private-key bytes.

## Implemented boundary

- `src/mpr_close_05_isolated_signer_jito_canary.py` defines:
  - exact isolated-signer authorization envelope;
  - nonce/replay protection helper;
  - durable submission outbox evidence;
  - conservative Jito settlement semantics;
  - bounded canary latches requiring upstream MPR-CLOSE-01..04 evidence and independent second human approval.
- `scripts/verify_isolated_signer_boundary.py --strict --json` proves exact-message authorization fails closed on mutation and never grants runtime signing power.
- `scripts/verify_jito_settlement_semantics.py --strict --json` proves ACK and bundle ID are not terminal settlement and finalized reconciliation remains required.
- `scripts/verify_canary_latches.py --strict --json` proves unrestricted live/default-on canary are blocked.

## Safety boundary

This PR intentionally does not:

- read wallet/private-key bytes;
- sign transactions;
- open signer IPC/network sockets;
- submit to Jito/RPC;
- poll live bundle status;
- enable unrestricted live trading;
- make live canary available by default.

## Acceptance

```bash
python -m compileall -q src scripts tests
python scripts/verify_isolated_signer_boundary.py --strict --json
python scripts/verify_jito_settlement_semantics.py --strict --json
python scripts/verify_canary_latches.py --strict --json
python -m pytest -q tests/test_mpr_close_05_isolated_signer_jito_canary.py
```

## Follow-up after MPR-CLOSE-01..04 land

The default-off verifier should be wired into the release authority and PR200 qualification evidence. Real IPC transport, signer image digest, Jito bundle polling and final settlement reconciliation must remain blocked until the upstream evidence bundle is accepted and human approval is bound to the exact message proof.
