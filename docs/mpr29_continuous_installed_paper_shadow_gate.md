# MPR-29 — Continuous installed paper/shadow workload gate

This checkpoint turns the V11 MPR-29 roadmap scope into a deterministic,
side-effect-free evidence contract. It does not open a signer, submit a
transaction, mutate deployment state, or promote the system to live.

## Scope

The gate covers the sender-free runtime boundary for:

- one installed paper/shadow runtime graph shared across safe-idle, paper,
  shadow and live-gate capability profiles;
- lifecycle truth for expiry, rejection, cancellation and terminal outcomes;
- workload readiness based on real workers, provider freshness, durable state
  and exact-simulator presence;
- bounded shutdown with structured concurrency and no orphaned writes;
- 24h pre-soak plus 72h soak with replay-stable evidence;
- installed-artifact execution only, with sender/signer/live namespaces absent.

## Safety boundary

A passing report still returns:

```text
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
```

A green report only means that MPR-30 may begin to depend on one continuous,
installed, sender-free workload proof. It is not a permit to sign, dispatch or
promote a live transaction.

## Verification

```bash
python -m py_compile \
  src/mpr29_continuous_installed_paper_shadow_gate.py \
  tests/test_mpr29_continuous_installed_paper_shadow_gate.py
python -m pytest -q tests/test_mpr29_continuous_installed_paper_shadow_gate.py
```