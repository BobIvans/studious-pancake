# PR-187 — Canonical paper-outcome authenticity and durable success semantics

## Mission

Prevent the exact-attempt adapter from converting a caller-controlled object or
non-empty strings into authoritative paper success.

`READY_FOR_DURABLE_PAPER` is now an exact-attempt handoff state. It is not a
settlement, durable outcome, metrics success, or soak success.

## Active runtime correction

`src/paper_shadow/a2_exact_attempt_runtime.py` now:

- validates every supplied digest as lowercase SHA-256;
- rejects the reproduced `not-a-hash`, `x`, `y` result;
- requires attempt, message, planner and reconciliation references for handoff;
- maps `READY_FOR_DURABLE_PAPER` to `EXACT_ATTEMPT_READY_FOR_HANDOFF`;
- marks handoff as not ready for the next cycle until durable outcome commit;
- requires the canonical `ExactPaperAttemptOrchestrator` in production;
- exposes a separately named test-only double seam;
- derives typed operation identity from exact request plus generation;
- preserves provider/capital/planner/compile/simulation/reconciliation/final-fee
  failure stages;
- continues after candidate-local rejection while stopping on dependency-wide or
  security failures.

## One durable paper-outcome authority

`src/paper_shadow/paper_outcome_pr187.py` writes to the existing lifecycle SQLite
connection. It does not introduce a second runtime database.

An authoritative envelope binds:

- exact attempt ID and generation;
- logical opportunity and exact request hash;
- typed operation ID;
- plan, message, simulation and reconciliation hashes;
- provider, policy and release evidence;
- existing lifecycle event ID;
- durable paper-outcome event ID;
- terminal capital-reservation state;
- canonical producer and verifier identities;
- explicit success or failure result.

The commit is atomic with reservation terminalization:

- successful paper outcome consumes the paper reservation;
- failed paper outcome releases it.

Replay verification checks the stored envelope digest, durable attempt identity,
lifecycle-event reference, reservation terminal state, producer identity and the
absence of sender/submission surfaces.

Only `VERIFIED_SUCCESS` has `counts_as_soak_success=true`.

## Safety invariants

```text
READY_FOR_DURABLE_PAPER != paper success
non_empty_string != evidence
fake production orchestrator = rejected
uncommitted handoff counts toward soak = false
sender imported = false
submission allowed = false
live enabled = false
```

## Verification

```bash
python -m pytest \
  tests/test_a2_exact_attempt_runtime.py \
  tests/test_pr187_paper_outcome_authenticity.py -q
python -m compileall -q src tests
```

## Remaining integration

The supported A2 recorded-evidence runtime and later soak/metrics workflows must
consume `PaperOutcomeVerification`, not descriptor-only A2 handoff records.
No live, signer, Jito or RPC submission path is added by PR-187.
