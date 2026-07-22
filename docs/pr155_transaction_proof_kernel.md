# PR-155 — Canonical transaction proof kernel

This PR adds a side-effect-free proof contract for the snapshot-9 PR-155 scope.
The new queue maps PR-155 to the canonical transaction proof layer that sits
after policy/admission and market/economics work and before durable paper
runtime integration.

## What this slice adds

- `src/transaction_proof_pr155.py`
  - one canonical v0 transaction proof contract;
  - absolute full signed wire ceiling of 1232 bytes;
  - exactly one transaction for the first sender-free vertical;
  - expected payer and signer-set binding;
  - semantic instruction firewall for supported programs;
  - fail-closed unknown program/instruction handling;
  - compute-budget uniqueness and final fee evidence checks;
  - blockhash/min-context/last-valid-height proof;
  - reviewed ALT content/order/owner evidence;
  - simulation-owned raw account/log/inner-instruction evidence;
  - planned/top-level/CPI graph comparison;
  - conservative reconciliation with principal, flash fee, fees, tip, rent,
    slippage and net outcome;
  - domain-separated report hash.

- `tests/test_pr155_transaction_proof_kernel.py`
  - happy-path proof;
  - legacy transaction rejection;
  - multi-transaction rejection;
  - 1232-byte full-wire ceiling;
  - payer/signer mismatch;
  - unknown program fail-closed;
  - instruction amount mutation rejection;
  - unauthorized close/delegate/authority mutation guard;
  - duplicate compute-budget instruction rejection;
  - invalid blockhash and ALT rejection;
  - truncated simulation rejection;
  - unexpected CPI rejection;
  - double-counted flash fee rejection;
  - placeholder hash rejection;
  - one-byte proof-hash invalidation;
  - no sender/signing token guard.

## Non-goals

- No transaction compilation.
- No signing.
- No RPC.
- No Jito/Helius/MarginFi/Jupiter network calls.
- No private key loading.
- No sender/live/canary enablement.
- No active runtime rewiring in this slice.

## Suggested verification

```bash
python -m pytest tests/test_pr155_transaction_proof_kernel.py -q
python scripts/verify_repo.py --skip-dependency-audit
```

## Follow-up integration

Later PR-155 integration can feed this kernel from the real compiler, semantic
instruction firewall, simulator, CPI decoder, compute/blockhash/ALT finalizer
and reconciliation pipeline. PR-156 should consume only proven reports from this
kernel before creating durable sender-free paper outcomes.
