# PR-068 — AI advisory model registry/evaluation/drift/A-B evidence

This PR adds the first **AI advisory-only** evidence gate for the optional
post-PR-064 promotion track described in the 2026-07-21 remediation plan.

## Scope

PR-068 covers:

- model registry identity;
- pinned model, prompt, feature-schema and dataset hashes;
- time-split or walk-forward evaluation evidence;
- calibration and latency thresholds;
- drift monitor evidence;
- automatic-disable evidence;
- shadow A/B evidence;
- proof that the model took **zero live decisions**.

The implementation is intentionally offline and fail-closed.

## Non-scope

This PR does **not**:

- enable live trading;
- allow AI to approve, block, size or submit trades;
- call an LLM provider;
- call RPC/Jito/route providers;
- integrate with sender, signer, paper runner or canary runtime;
- claim a real model has already passed production review.

A passing PR-068 gate means only:

```text
advisory-evidence-ready
```

It does not mean:

```text
ai-can-trade
```

## Evidence objects

`src/ai_advisory/evidence_gate.py` defines:

- `ModelRegistryEntry`
- `ModelEvaluationReport`
- `DriftMonitorReport`
- `ShadowABReport`
- `AIAdvisoryEvidencePackage`
- `AIAdvisoryReadinessGate`

The gate returns `AIAdvisoryReadinessResult` with:

```text
ai_authority_enabled=false
trading_mutation_allowed=false
```

for every result, including passing results.

## Fail-closed blockers

The gate emits stable blocker codes, including:

- `MODEL_TRADING_AUTHORITY_ENABLED`
- `TIME_SPLIT_EVALUATION_MISSING`
- `EVALUATION_SAMPLE_TOO_SMALL`
- `EVALUATION_METRIC_BELOW_THRESHOLD`
- `CALIBRATION_ERROR_TOO_HIGH`
- `DRIFT_AUTODISABLE_MISSING`
- `AB_LIVE_DECISIONS_PRESENT`
- `AB_AUTOMATIC_DISABLE_MISSING`

## Review commands

```bash
python -m pytest tests/test_pr068_ai_advisory_evidence.py -q
python -m compileall -q src/ai_advisory tests/test_pr068_ai_advisory_evidence.py
```

## Integration guidance

Future runtime integration should consume only the readiness result and should
continue to treat AI as advisory-only. Any attempt to convert this into a trade
approval signal should require a separate architecture PR and must preserve the
existing capital, simulation, reconciliation, canary and sender safety gates.
