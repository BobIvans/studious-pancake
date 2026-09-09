# MPR-2607 — residual shadow-soak qualification

## Scope

This PR intentionally does **not** add another shadow runtime, campaign runner,
ledger, signer, telemetry stack, chaos driver, sealer, or product-readiness
authority. Existing continuous-soak work remains owned by the established
PR-060/PR-079/PR-092/PR-105 chain and by the still-open historical #275/#428
integration work.

The residual delta is an independent evidence consumer in
`src/shadow_soak/campaign_evidence.py` plus focused regression tests.

## What the residual consumer proves

- Real-shadow duration is recomputed from the union of evidenced eligible
  intervals; overlapping/parallel workers cannot multiply elapsed time.
- Calendar span, eligible coverage, longest policy-continuous window, and gaps
  are reported separately.
- Synthetic and recorded-replay intervals receive no real-duration credit.
- Replay execution count cannot extend a real campaign.
- Exact duplicate terminal deliveries count once; the same outcome identity
  with changed semantics is a conflict.
- Equal semantic payloads from distinct real observation/outcome identities are
  not collapsed merely because their bytes match.
- Claimed summary duration and terminal counts are checked against recomputed
  raw evidence, preventing summary-only promotion.
- Fault/downtime/blocked intervals remain visible in calendar span but do not
  become eligible coverage.
- `evaluate_real_shadow_soak_residual()` composes these checks with the existing
  PR-079 evaluator and always keeps `live_allowed=False`.

## Ownership / anti-duplication disposition

| Area | MPR-2607 disposition |
| --- | --- |
| runtime / capital / lifecycle | reuse existing owners; no change |
| provider accounting / planner / simulation | reuse upstream owners; no change |
| campaign loop / collector | owned elsewhere; no second runner |
| telemetry / latency instrumentation | owned elsewhere; no second stack |
| fault driver | reuse existing harness; no second chaos runtime |
| release sealing / signatures | owned elsewhere; no new authority |
| raw interval coverage recomputation | residual consumer added here |
| duplicate/conflicting terminal evidence | residual consumer added here |
| summary-vs-raw claim reconciliation | residual consumer added here |
| real elapsed campaign | **not run by this PR** |

## Verification target

Focused test file:

```text
tests/test_mpr2607_campaign_evidence_residuals.py
```

It covers overlap union, gaps, permitted-gap continuity without duration
inflation, lineage separation, replay exclusion, duplicate delivery, semantic
identity conflict, distinct observations with equal payloads, summary forgery,
and exclusion of fault/downtime/blocked intervals.

## Qualification boundary

This implementation can be `IMPLEMENTED` / `VERIFIED_OFFLINE` after tests pass.
It is **not** evidence of a real 72-hour (or longer policy-required) campaign.
No RPC probe, signing, transaction submission, bundle submission, wallet action,
or live promotion is performed by MPR-2607.

A future operator-run campaign must supply accepted producer evidence and the
actual policy thresholds. `READY_FOR_REVIEW` or a green CI run must not be
reported as `REAL_SHADOW_QUALIFIED` or `LIVE_READY`.
