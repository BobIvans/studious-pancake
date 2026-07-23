# MPR-04 — Isolated signer, Jito semantics and live-canary boundary

## Status

This branch starts **MPR-04** as a safe additive slice.
It does **not** enable unrestricted live trading, signer access from runtime,
RPC/Jito submission, or private-key handling inside the main runtime.

The implementation is an offline acceptance contract that defines what must be
proven before the repository can claim a reviewed isolated-signer boundary and a
budgeted live-canary boundary.

## Why this slice exists

The mega-PR pack assigns MPR-04 to the boundary where:

- runtime never owns private-key bytes;
- signer authorization binds exact message hash and policy/config/evidence identity;
- durable submission intent exists before transport;
- Jito ACK or bundle ID never counts as settlement;
- canary is gated by real evidence, budgets, emergency stop and second-human approval;
- unrestricted live remains unavailable by default.

This slice makes those requirements explicit and testable without activating any
side effect.

## Added files

- `src/mpr04_isolated_signer_canary_gate.py`
- `tests/test_mpr04_isolated_signer_canary_gate.py`
- `docs/mpr04_isolated_signer_jito_canary_boundary.md`
- `.github/workflows/mpr04-isolated-signer-canary.yml`

## What the gate requires

The evaluator blocks unless evidence proves all of the following:

1. **Isolated signer contract**
   - runtime has no private-key access;
   - isolated signer process is required;
   - exact message hash is bound;
   - policy hash, config generation, reservation, wallet and market/provider identity are bound;
   - nonce and expiry are enforced.

2. **Exactly-once submission intent**
   - durable submission intent is written before transport;
   - replay is denied;
   - stale config, stale shadow evidence and stale human approval are denied.

3. **Jito semantics are conservative**
   - ACK is not settlement;
   - bundle ID is not settlement;
   - finalized settlement is required;
   - tip budget, rate limit and unbundling protections exist;
   - transaction-local safety assertions remain enforced.

4. **Canary latches are real**
   - fresh production cutover manifest;
   - MPR-01/02/03 evidence present;
   - no unknown outstanding attempts;
   - capital/day/loss caps enforced;
   - emergency stop clear required;
   - exact message proof required;
   - final human approval bound to exact message hash.

5. **Promotion stays controlled**
   - at least two distinct fresh independent approvals;
   - unrestricted live remains unavailable;
   - live canary is not available by default.

## Safety boundary

A passing report still returns:

```text
signer_allowed=false
sender_allowed=false
live_execution_allowed=false
live_canary_allowed=false
```

So this branch is a foundation slice, not an activation slice.

## Relationship to the mega-PR pack

This branch covers the first safe checkpoint of MPR-04 from the uploaded pack:
isolated signer contract, anti-replay submission intent, conservative Jito
semantics and canary latches. Later MPR-04 checkpoints must wire these
invariants into the real isolated signer service, durable submission stores,
actual Jito/RPC transport logic and reviewed live-canary control flow.

## Focused verification

```bash
python -m py_compile \
  src/mpr04_isolated_signer_canary_gate.py \
  tests/test_mpr04_isolated_signer_canary_gate.py
python -m pytest -q tests/test_mpr04_isolated_signer_canary_gate.py
```

## Not included yet

This slice intentionally does not:

- load or export private keys;
- start a signer process;
- open RPC or Jito connections;
- submit transactions;
- mark ACK or bundle receipt as settlement;
- enable unrestricted live;
- make canary available by default.
