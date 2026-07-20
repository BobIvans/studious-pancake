# PR-063 hardening — authoritative sender status consolidation

## Context

The canonical Jito/RPC sender from roadmap PR-063 is already merged in
`src/submission/canonical_sender.py`. This follow-up does not create another
sender, credential model, transport factory, or public submission stack.

It hardens the missing post-submit boundary: one conservative decision across
Solana signature evidence and optional Jito delivery evidence.

## Authority model

`getSignatureStatuses` is the canonical source for transaction landing and
on-chain failure. Jito inflight and durable bundle statuses are supplementary:

- Jito `Landed` without a confirmed/finalized Solana signature remains
  `unknown`;
- a confirmed/finalized Solana signature remains landed even when a stale Jito
  cache reports failure;
- a Solana on-chain error remains failed;
- blockhash expiry becomes ambiguous when Jito still reports accepted, landed,
  or indeterminate delivery evidence;
- processed Solana evidence conflicting with Jito failure remains ambiguous.

Exactly one aggregate Solana observation is required. RPC-only status reports
reject Jito observations.

## No duplicate submission

Every `CanonicalStatusReport` has:

```text
automatic_resubmit_allowed = false
resend_same_payload_allowed = false
```

Ambiguous states map to `RECONCILE_WITHOUT_RESEND`. Proven expiry or on-chain
failure can only map to `REVIEWED_REBUILD_NEW_PERMIT`, using the merged PR-063
follow-up policy. The old signed payload is never replayed.

## Bounded polling

`poll_canonical_status_once(...)` performs one bounded status pass:

1. poll Solana signature status;
2. for a Jito acknowledgement with a bundle ID, poll inflight status;
3. poll durable bundle status;
4. consolidate without sending, transport fallback, or retry.

The acknowledgement transport must match the selected canonical stack before
any network call.

## Files

- `src/submission/canonical_status.py`
- `tests/test_pr063_status_consolidation.py`
- `tests/fixtures/pr063/official_status_contract.json`
- this document
- additive exports in `src/submission/__init__.py`

## Parallel-work safety

The patch does not modify the merged canonical sender implementation, active
runner composition, signer, planner/compiler/simulation/reconciliation,
capital reservations, external-contract registry, canary, release gates,
Phoenix, Kamino, or live activation controls.

## Verification

```bash
python -m black --check \
  src/submission/canonical_status.py \
  tests/test_pr063_status_consolidation.py
python -m mypy --config-file mypy.ini src/submission
python -m pytest \
  tests/test_pr063_canonical_sender_consolidation.py \
  tests/test_pr063_status_consolidation.py \
  -q --disable-socket --allow-unix-socket
python -m compileall -q \
  src/submission/canonical_status.py \
  tests/test_pr063_status_consolidation.py
python scripts/verify_repo.py
```
