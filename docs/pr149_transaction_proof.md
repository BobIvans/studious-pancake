# PR-149 — Canonical transaction, instruction firewall and simulation-owned proof

This starts the snapshot-9 roadmap PR-149 as a low-conflict additive review gate.

The roadmap defines PR-149 as the step that turns an exact candidate into one
fully proven sender-free v0 transaction: canonical execution domain, semantic
instruction firewall, compute/fee finalization, blockhash/ALT/fork proof,
simulation-owned raw evidence, CPI graph and conservative reconciliation.

## Added files

- `src/transaction_proof_pr149.py`
- `tests/test_pr149_transaction_proof.py`
- `docs/pr149_transaction_proof.md`

## Contract

The gate is side-effect-free and fail-closed. It checks:

- exactly one canonical v0 transaction;
- full signed wire size within the 1232-byte ceiling;
- exact payer, signer set, account privilege hash and ALT hash;
- blockhash validity, last-valid height and min-context evidence;
- exactly one final compute-budget finalization and final fee proof;
- decoded System, ATA, SPL Token, Token-2022, Jupiter, MarginFi and route instructions;
- rejection of unknown/opaque/unsafe instructions, amount mismatch, authority change,
  arbitrary transfers and close/delegate behavior;
- simulator-owned raw accounts/owners/data/balances/token balances/loaded addresses/
  inner instructions/logs/return data evidence;
- planned/top-level/CPI program matching and CPI allowlisting;
- conservative repayment, fee and unauthorized-mutation reconciliation;
- deterministic proof hash invalidation for any evidence change.

## Safety

This slice does not import or invoke a sender, signer, RPC client, Jito, Helius,
Jupiter or MarginFi. It does not change active planner/compiler/simulator/runtime
wiring and does not enable paper/live execution. `sender_submission_allowed` and
`live_claim_allowed` remain false.

## Parallel compatibility

No shared high-churn files are edited:

- no `config/format_targets.txt`;
- no `scripts/verify_repo.py`;
- no workflow files;
- no Dockerfile or lock files;
- no active planner/compiler/simulator/sender/runtime modules.

## Focused local verification

```bash
python -m py_compile src/transaction_proof_pr149.py tests/test_pr149_transaction_proof.py
PYTHONPATH=/mnt/data/pr149b python -m pytest -q tests/test_pr149_transaction_proof.py
# 11 passed
```
