# SUPER-04 — treasury, owned ALT, atomic batch and transaction-format evidence

SUPER-04 executes **W2-11 + W2-12** without creating a second signer, sender,
ledger, compiler or runtime authority.

## Implemented offline

- PR-073 / NF-329..332: integer-only fee-reserve replenishment planning,
  quote binding, durable operation identity and unknown-outcome reconciliation.
- PR-076 / NF-341..344: default-off owned ALT planning, pinned pure unsigned
  create/extend/deactivate/close builders, readiness validation and retirement
  guards.
- PR-074 / NF-333..336: immutable multi-intent parent membership, bounded
  composition, integer cost attribution/floors and parent-to-child settlement.

These paths are sender-free. They do not load private keys, sign, submit,
fund wallets, mutate provider resources, or enable live trading.

## PR-078 disposition: BLOCKED, not fabricated

The current canonical owner
`src.execution.transaction_compiler.TransactionCompiler` compiles
`MessageV0`. The repository does not contain a qualified v1 unsigned
compiler/decoder path.

`src/execution/transaction_format_qualification.py` therefore records the
required pinned SDK/source/license/capability evidence and fails closed with
`V1_CANONICAL_COMPILER_NOT_IMPLEMENTED` even when external capability
evidence is otherwise complete.

A future PR may close PR-078 only after an actual supported v1 codec is pinned,
licensed, integrated under the existing compiler owner, exact-simulated,
permit-bound and finalized through the same settlement authority.

## Status

- implementation: **PARTIAL**
- qualification: **BLOCKED**
- activation: **DEFAULT_OFF**
- live/signing/submission: **false**

Merging SUPER-04 accepts the offline code/evidence closure only. It does not
make the repository production-ready and does not authorize any transaction.
