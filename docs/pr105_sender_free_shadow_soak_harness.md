# PR-105 — sender-free real shadow-soak harness

This PR starts the roadmap PR-105 scope from snapshot `(8)` without claiming that
a real 72-hour soak has already happened.

## What this adds

`src/shadow_soak/pr105_harness.py` defines a reviewable sender-free harness plan
for a real shadow/mainnet-read-only soak run:

- normalized run id and artifact layout;
- minimum duration of 72 hours;
- PR-092 artifact targets;
- required telemetry streams for discovery, capital, planner, compiler,
  simulation, reconciliation and lifecycle;
- rejection, latency, quota, staleness, message-hash and repayment telemetry;
- a progress snapshot evaluator that can mark the harness ready for PR-092
  manifest assembly only after the run is finalized and all planned artifacts
  are materialized.

## Safety boundary

This PR does not enable live trading.  The harness plan always reports:

```text
live_allowed = false
sender_enabled = false
submission_endpoints_enabled = false
pr092_evidence_claimed = false
```

The snapshot evaluator always reports:

```text
live_allowed = false
runtime_submission_enabled = false
```

Observed sender imports, enabled submission endpoints, or any live submissions
block readiness even if the run lasted more than 72 hours.

## Why this is not full PR-105 completion

Roadmap PR-105 asks for an actual 72-hour run and an immutable artifact bundle.
A code patch cannot honestly create that operational evidence.  This PR only
adds the harness contract needed to run and collect it later.

After a real run finishes, the operator still must create the PR-092 manifest
and pass `evaluate_pr092_actual_shadow_soak(...)` against existing materialized
files and verified hashes.

## Suggested verification

```bash
python -m pytest tests/test_pr105_shadow_soak_harness.py -q
python -m pytest tests/test_pr092_actual_soak.py tests/test_pr105_shadow_soak_harness.py -q
python -m black --check src/shadow_soak/pr105_harness.py tests/test_pr105_shadow_soak_harness.py
python scripts/verify_repo.py --skip-dependency-audit
```

## Non-goals

- no MarginFi/Jupiter execution implementation;
- no wallet/signing;
- no RPC/Jito submission;
- no sender import;
- no automatic soak claim;
- no live/canary enablement.
