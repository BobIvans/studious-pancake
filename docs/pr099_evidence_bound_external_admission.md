# PR-099 — Evidence-bound external admission

This patch starts the roadmap PR-099 scope from current `main`.

It fixes the first critical admission failure described by the snapshot `(8)` audit:
a locally active, composable Jupiter contract must not become runtime-executable
while its decisive contract evidence still says execution is not allowed.

## What changed

- Adds a shared external contract admission policy in
  `src/external_contracts/policy.py`.
- Updates `evaluate_runtime_admission(...)` so Jupiter execution admission uses:
  - contract status;
  - composable capability;
  - `contract.execution_allowed`;
  - `promotion_state == execution-allowed`;
  - required credential availability.
- Keeps MarginFi disabled and live hard-denied.
- Updates online conformance CLI exit semantics:
  - assertion/request failure stays exit `2`;
  - explicitly requested online conformance that skips due missing env/probe is
    now exit `3`;
  - optional/not-requested skips remain exit `0`.
- Adds focused PR-099 regression tests.

## Safety boundary

This PR does not add MarginFi execution, paper stages, sender, signer, Jito
submission, wallet mutation, canary enablement or live trading. It is an
admission hardening slice only.

## Remaining PR-099 work

This patch intentionally keeps the first slice narrow so it can merge cleanly
while other chats are landing adjacent roadmap PRs. Remaining PR-099 hardening
should follow in subsequent slices:

- bind `ProviderRegistry` roles to the same policy;
- remove legacy conformance transport assertion bypass;
- strengthen packaged Jito/OKX/Odos probes;
- require materialized conformance evidence artifacts for promotion.

## Suggested verification

```bash
python -m pytest tests/test_pr099_evidence_bound_external_admission.py -q
python -m pytest tests/test_pr070_protocol_aware_conformance.py tests/test_pr099_evidence_bound_external_admission.py -q
python scripts/verify_repo.py --skip-dependency-audit
```
