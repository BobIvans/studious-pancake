# PR-116 — Coherent rooted MarginFi snapshot and oracle freshness

This PR adds a sender-free, RPC-free evidence gate for roadmap PR-116. It does
not change the live runner, planner, sender, signer, RPC transport, Jito, or
canary behavior.

## Problem

The deep audit found that the current MarginFi reader can read the base protocol
accounts in one RPC context and then read additional banks/vaults in a later
context, while the resulting snapshot is labelled with the later slot. That can
mix bytes from two states and hide the slot vector inside one fingerprint.

The audit also requires oracle accounts and oracle freshness to be part of the
snapshot evidence before MarginFi can be considered paper-ready.

## What this patch adds

- `src/providers/marginfi/coherent_snapshot.py`
  - PR-116 schema and result schema;
  - account-role evidence for program, ProgramData, group, margin account,
    target bank, active banks, vaults and oracles;
  - RPC batch evidence with context slot, minContextSlot, rooted slot,
    response hash and address set;
  - oracle freshness and bank relationship evidence;
  - a state fingerprint that hashes address, role, owner, data hash and slot;
  - `evaluate_marginfi_coherent_snapshot(...)`;
  - `assert_marginfi_coherent_snapshot(...)`.
- Focused tests for mixed-slot rejection, oracle staleness, oracle relationship,
  multi-call slot-vector verification, fingerprint mismatch and live denial.
- Exports from `src.providers.marginfi`.
- Adds the PR-116 files to Black and focused repository verification.

## Safety boundary

A passing PR-116 evaluation means only:

```text
marginfi-readonly-coherent-snapshot-capable
```

It still returns:

```text
live_execution_allowed = false
```

## Non-goals

- No live trading.
- No RPC calls.
- No sender import.
- No signer or wallet access.
- No Jito/RPC submission.
- No planner/paper execution enablement.
- No claim that real PR-116 mainnet evidence is already present.

## Follow-up operational evidence

Operators still need to materialize real read-only RPC evidence, including
program/ProgramData, group, margin account, target and active banks, liquidity
vaults and oracle accounts, and then sign/review that evidence before using this
gate as part of a later paper-ready package.
