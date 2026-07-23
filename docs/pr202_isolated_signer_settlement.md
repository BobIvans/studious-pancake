# PR-202 — isolated signer, reviewed permit, one sender and finalized settlement foundation

This patch starts the new consolidated roadmap **PR-202 — Isolated signer,
reviewed permit, one sender and finalized settlement**.

## Safety boundary

No live trading, wallet loading, private-key loading, signing, transaction
construction or transaction submission is introduced. The implementation is an
additive, default-off evidence authority that can be wired into the PR-196
runtime kernel and PR-201 deployment plane later.

## What this slice enforces

`src/submission/pr202_isolated_signer_settlement.py` adds fail-closed primitives
for:

- isolated signer boundary evidence: separate process/container, narrow IPC,
  no key material in main runtime/logs/files, deny-by-default egress, no general
  network access and no unreviewed signing method;
- short-lived reviewed permits bound to release/config/policy/attempt/plan,
  message hash, blockhash, transport, tip, risk budget and monotonic boot
  generation;
- one durable SQLite-backed permit-consumption authority per attempt;
- submission intent recorded before any transport acknowledgement;
- one selected transport per attempt with fallback/resend of the same payload
  rejected;
- ACK semantics that cannot create realized PnL;
- finalized settlement only from signature finality, transaction meta, native and
  token balance delta hashes, repayment verification and minimum rooted slot;
- ambiguous transport outcomes locked for manual review;
- combined PR-202 readiness report that keeps live/signer/sender/submission
  disabled.

## Findings covered by this foundation

This directly targets the PR-202 roadmap concerns around isolated key custody,
reviewed single-use permits, replay/reuse rejection, one sender/one transport,
Jito/RPC ACK separation from settlement, crash-safe submission intent, finalized
reconciliation, secret rotation and signer-compromise drill evidence.

It intentionally does not claim full PR-202 completion yet. Remaining work
includes the real isolated signer process/service, narrow IPC implementation,
PR-196 transaction-bound composition, transport-specific Jito/RPC sender adapter,
real signature-status reconciliation, operator break-glass controls, network
egress policy enforcement and release-approved live activation after PR-01
through PR-201 prerequisites are accepted.

## Verification

```bash
python -m pytest -q tests/test_pr202_isolated_signer_settlement.py --disable-socket --allow-unix-socket
python -m py_compile \
  src/submission/pr202_isolated_signer_settlement.py \
  tests/test_pr202_isolated_signer_settlement.py
```

Formatter/typecheck enrollment is intentionally not added to `config/format_targets.txt`
or `mypy.ini` in this PR because those manifests are high-conflict parallel
roadmap surfaces. PR-194 remains the right vertical for full production-surface
quality baseline expansion.

## Rollback

The patch is additive and default-off. Reverting the PR removes the focused
workflow, module, docs and tests without touching active runtime paths, provider
configuration, wallet/signing code, sender adapters or deployment manifests.
