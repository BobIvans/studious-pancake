# PR-037 — state-based economic reconciliation

PR-037 introduces a sender-free, fail-closed reconciliation boundary for exact
simulation evidence. It proves the economic outcome from typed pre/post account
state; transaction logs are retained only as hashed diagnostics and can never
prove repayment or profit.

## Dependency and integration boundary

The roadmap dependencies, PR-028 and PR-036, are present on `main`.

- PR-028 owns MarginFi binary decoding and instruction conformance.
- PR-036 owns exact-message simulation, compute-budget finalization, targeted
  RPC account collection, response/log hashes, fee quotation, and retry
  classification.
- `evidence_from_exact_simulation` binds PR-037 to PR-036's exact final message,
  ordered returned-account hashes, final slot, minContextSlot, and fee quote.
- PR-037 does not edit the PR-036 simulator or introduce another RPC path.
- The new package is `src.execution.economic_reconciliation`; the existing
  `src.execution.reconciliation` module and its public lifecycle API remain
  unchanged.
- PR-038 can consume the immutable economic report in the durable paper/shadow
  runner.

## Evidence contract

A complete reconciliation requires matching final message hashes, matching
ordered account hashes, one accepted slot, complete declared account
lifecycles, exact integer fee evidence, and decoded MarginFi repayment state.
Missing or inconsistent evidence returns `indeterminate`; it never becomes a
zero-valued success.

## Token and lifecycle rules

- Native SOL, SPL Token, and Token-2022 use separate typed asset identities.
- Mint, token program, decimals, authority, program owner, and extension set
  must remain consistent across pre/post state.
- Unknown token programs fail closed.
- The initial Token-2022 policy allows only the reviewed `immutable_owner`
  account extension.
- ATA/wSOL rent is measured from explicit created/closed state transitions.
- Token base units are never mixed with lamports.

## Repayment proof

A log containing `repay` is not evidence. The bounded MarginFi vertical requires
program ownership, zero target liability before/after, clear flash-loan flags,
positive ordered borrow/repayment amounts, and the exact vault invariant:

```text
vault_after == vault_before - borrowed + required_repayment
```

The derived protocol fee is `required_repayment - borrowed_amount`.

## Economic decomposition

For each asset independently:

```text
gross
- protocol fee
- base network fee
- priority fee
- tip
- rent locked
+ rent refunded
= observed net
```

Network fee, priority fee, tip, and rent remain native-SOL quantities. No token
conversion occurs without a separate valuation contract.

## Focused checks

```bash
python -m pytest tests/execution/test_economic_reconciliation_pr037.py -q
python -m black --check src/execution/economic_reconciliation \
  tests/execution/test_economic_reconciliation_pr037.py
python -m mypy src/execution/economic_reconciliation
```

The fixtures cover profit, loss, partial state, Token-2022, ATA rent, failed
repayment, log-only false evidence, message/slot binding, unsupported token
programs/extensions, and the merged PR-036 adapter.

## Safety state

This PR adds no signer, sender, permit, bundle, RPC submission, or live-mode
activation. Runtime composition remains owned by PR-038.
