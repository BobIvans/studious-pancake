# MEGA-PR-03 — Default-off live authorization boundary checkpoint

This checkpoint starts the V5 **MEGA-PR-03** work without enabling live trading.  It
adds an offline acceptance gate that forces permit, message, wire, transport,
tip, settlement and resubmission identity to remain one immutable chain before
any future signer or sender integration may consume the evidence.

## Why this exists

The V5 audit shows that live canary remains blocked while:

- permit consumption does not check current block height;
- permits are process-local or unauthenticated;
- tip evidence is caller-created;
- resubmission can bypass archive-complete proof;
- transport/tip identity can drift after consumption;
- legacy journal/live-control paths remain reachable.

This file intentionally does not claim full MEGA-PR-03 completion.  The full
cutover still needs durable permit issuance/consumption, authenticated signer IPC,
wire-byte parsing, one sender, rooted settlement, treasury authority and deletion
or hard-disablement of legacy live paths.

## Added surface

- `src/live_boundary/mega_pr03_live_authorization_gate.py`
- `tests/test_mega_pr03_live_authorization_gate.py`
- `.github/workflows/mega-pr03-live-authorization-boundary.yml`

## Checkpoint guarantees

The gate fails closed when any of the following is true:

- live runtime is enabled or a legacy live path is still reachable;
- permit is not yet valid, expired or lacks remaining block-height margin;
- first generation lacks explicit predecessor absence evidence;
- resend generation lacks archive-complete resend authorization hash;
- permit message/blockhash/transport/tip identity differs from signed wire evidence;
- submission intent changes permit hash, attempt generation, signed tx, blockhash,
  transport, tip or resend authorization;
- settlement transport/tip/message identity differs or is not rooted-finalized;
- unsigned reviewer DTOs or bool/float monetary/height fields are supplied.

## Safety boundary

This checkpoint is sender-free and offline.  It does not:

- sign transactions;
- submit transactions;
- call Solana RPC, Jito, Jupiter, Helius, MarginFi or Kamino;
- load private keys or signer IPC;
- make live runtime reachable.

The successful state is deliberately named `READY_DEFAULT_OFF`, not `LIVE_READY`.

## Verification

```bash
python -m py_compile \
  src/live_boundary/mega_pr03_live_authorization_gate.py \
  tests/test_mega_pr03_live_authorization_gate.py
python -m pytest -q tests/test_mega_pr03_live_authorization_gate.py
```

## Remaining MEGA-PR-03 cutover work

1. Replace the in-memory/process-local permit issuer with a durable MPR-19-backed
authority and unique attempt+generation+message constraints.
2. Parse signed VersionedTransaction bytes inside the signer/sender boundary and
re-derive the Jito tip from wire bytes.
3. Require current-height/root evidence during permit consumption.
4. Require PR-197 archive-complete authorization for every generation > 1.
5. Bind transport/tip/blockhash/message identity through ACK, finalized settlement
and treasury ledger.
6. Delete or make unreachable legacy PR-014/PR-018 journal/live-control paths.
