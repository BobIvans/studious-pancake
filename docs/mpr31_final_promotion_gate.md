# MPR-31 final promotion gate foundation

This document describes the default-off foundation gate added for **MPR-31 — Treasury, live-canary, operations, immutable archive and final production promotion**.

The gate is intentionally offline and non-destructive. It does **not** enable live trading, signer IPC, transaction submission, treasury movement, archive writes, operator sessions or live-canary execution.

## Purpose

MPR-31 is the only roadmap vertical that may eventually change production promotion or live-canary status. This foundation PR does not do that cutover. It defines the evidence contract that a later destructive cutover must consume before a tiny controlled canary can be considered.

## Evidence required

`MPR31FinalPromotionGate` requires all of the following before it can return `READY_DEFAULT_OFF`:

- signed immutable upstream evidence from `MPR-25`, `MPR-26`, `MPR-27`, `MPR-28`, `MPR-29` and `MPR-30`;
- source, wheel, image, config and policy digests;
- rooted treasury evidence for wallet balance, token inventory, provider quorum and policy generation;
- zero unresolved exposure, no hard latch and loss values within the canary limit;
- immutable archive evidence with replay verification from remote receipts;
- authenticated operator command evidence with a valid not-before/expiry window;
- exactly one manual canary transaction proposal;
- post-canary review requirement;
- no live expansion request;
- live runtime still default-off.

## Fail-closed blockers

The gate returns `BLOCKED` for missing, stale, future-dated, duplicate, unsigned or self-declared upstream evidence. It also blocks for unresolved treasury exposure, active hard latches, loss limit breaches, unverified archive replay, stale/future operator commands, multiple canary transactions, canary expansion requests and any attempt to request live runtime directly.

## Default-off semantics

The only green status is `READY_DEFAULT_OFF`. That status means the evidence bundle is internally consistent enough for a later promotion process to review. It does not make live runtime reachable and does not submit a transaction.

## Verification

Focused verification is provided by:

```bash
python -m py_compile \
  src/release_gate/mpr31_final_promotion_gate.py \
  tests/test_mpr31_final_promotion_gate.py
python -m pytest -q tests/test_mpr31_final_promotion_gate.py
```

## Remaining full MPR-31 work

This foundation does not complete the destructive production promotion cutover. Later work must wire the contract into the installed release qualification DAG, consume real evidence from MPR-25 through MPR-30, move treasury/live-canary state into a durable fenced authority, verify archive receipts from bytes, consume DR/soak evidence and keep live disabled until explicit final policy enables one tiny manual canary.
