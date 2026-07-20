# PR-029 — canonical execution domain

## Decision

Production callers import execution contracts from `src.execution`. That public
boundary exposes one strict `TransactionPlan → CompiledTransaction →
SimulationReport → ExecutionReceipt` lifecycle.

The public `TransactionCompiler` is `CanonicalTransactionCompiler`. It validates
all inputs before delegating to the existing Solders v0 implementation and then
proves that:

- payer, signers and account identities are `solders.pubkey.Pubkey` values;
- every planned instruction wraps `solders.instruction.Instruction`;
- the compiled message is `MessageV0`;
- message bytes, transaction bytes and SHA-256 message hash agree;
- no `b"unsigned:"` synthetic payload can cross the public boundary;
- signing preserves the exact message hash;
- transport receipts remain bound to that same hash.

## Quarantine and migration

`Instruction` and `FlashLoanPlan` string compatibility objects remain physically
present in `src.execution.models` only so older quarantined tests/modules can be
migrated in bounded follow-up changes. They are no longer exported by
`src.execution` and are not accepted by its compiler.

Direct imports of the legacy-aware compiler are deprecated. Maintained runtime
code must use:

```python
from src.execution import TransactionCompiler, TransactionPlan
```

The remaining physical deletion of compatibility definitions can happen after
all quarantined orderbook/legacy tests stop importing them. This does not weaken
the active boundary: a string payer or legacy instruction is rejected before
the legacy compiler branch is reachable.

## Invariants

1. One canonical SHA-256 hash is computed over serialized v0 message bytes.
2. Compile, simulate, permit, journal, sign and receipt stages use that hash.
3. Any changed byte invalidates downstream evidence.
4. Public execution types never accept strings in place of Solana identities.
5. Paper and live transports may differ, but their message identity does not.
6. Live remains default-deny; this PR adds no sender or enablement path.

## Rollback

Revert the PR commits. No database/config migration is introduced. The change is
limited to the Python public export boundary, validation code, tests and this
ADR.
