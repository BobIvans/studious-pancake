# MPR-NEXT-05 — Signer, Jito, finality and canary boundary

## Scope

This PR starts the default-off live/canary boundary described by the third-pass production audit. It prepares the semantic gate for an isolated signer and one-transaction canary, but it does **not** enable unrestricted live execution.

## Implemented slice

- `src/live_boundary/mpr_next_05_canary_boundary.py`
  - approval artifact with independent second reviewer;
  - exact runtime/config/capability digest binding;
  - one-transaction canary approval contract;
  - permit object bound to exact message, route, simulation, account metas and nonce;
  - filesystem-backed permit-consumption ledger;
  - signing request verifier that consumes a permit exactly once before returning a signing-intent digest;
  - kill-switch, fee/tip/loss/spend, program allowlist and Jito policy blockers;
  - Jito lifecycle state model;
  - finalized settlement proof model that requires finalized chain deltas.

## Explicit non-goals

This PR does not:

- sign messages;
- submit transactions;
- call RPC;
- call Jito;
- load private keys;
- open unrestricted live mode;
- treat Jito ACK, bundle id, signature string, submitted or landed state as economic settlement.

## Safety invariants

- `live_ready` remains false in the signing verdict.
- A successful canary signing request only becomes `ready-for-isolated-signer`; it does not produce a signature.
- A permit is consumed durably and cannot be reused after restart.
- A mutated message, route, simulation or account metas digest fails closed.
- Jito requires explicit canary policy and still cannot become settlement authority.
- Realized profit is allowed only after finalized transaction evidence and finalized account deltas.

## Focused verification

```bash
python -m py_compile \
  src/live_boundary/mpr_next_05_canary_boundary.py \
  tests/test_mpr_next_05_canary_boundary.py
PYTHONPATH=. python -m pytest -q tests/test_mpr_next_05_canary_boundary.py
```

## Follow-up wiring

Later work can wire this gate into the isolated signer service and submission boundary. That follow-up must still keep live default-off and require signed evidence from the paper/shadow, provider/protocol and durable economic authority PRs before any one-transaction canary can be armed.
