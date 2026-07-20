# PR-067 — Kamino lending/liquidation conformance gate

## Purpose

PR-067 adds a fail-closed evidence contract for Kamino lending/liquidation work.
It does not enable liquidation execution and does not add verified Kamino markets
to the default runtime registry.

The goal is to make a future Kamino promotion review explicit: before a
market/asset combination can be treated as shadow-ready, the repository must
carry digest-pinned evidence for source provenance, RPC golden account bytes,
SDK instruction vectors, health/oracle math, deterministic planner replay,
shadow-soak evidence, and human review.

## Added boundary

`src/lending/kamino_conformance.py` introduces:

- `KaminoConformanceEvidence` — immutable evidence envelope for one
  `KaminoSupportedCombination`;
- `KaminoConformanceArtifact` — digest-pinned references for IDL, RPC fixtures,
  instruction vectors, health/oracle report, planner replay, shadow-soak report,
  and human review;
- `KaminoRpcAccountVector` — owner/data/decoded-field digest checks for market,
  reserve, obligation and oracle account samples;
- `KaminoInstructionGoldenVector` — SDK-derived instruction account-meta and
  data digests;
- `KaminoHealthOracleMathEvidence` — bounded health-factor and oracle staleness
  evidence;
- `KaminoPlannerReplayEvidence` — deterministic replay corpus checks;
- `KaminoShadowSoakReference` — link to a PR-060 style soak artifact;
- `evaluate_kamino_conformance(...)` — fail-closed gate returning blockers and
  warnings.

## Default policy

The default threshold requires:

- at least 4 RPC golden account vectors;
- market, reserve, obligation and oracle vector kinds;
- at least 2 SDK instruction golden vectors;
- health/oracle math passed with <= 1 bps health-factor error;
- price staleness <= 10 slots;
- deterministic planner replay with zero mismatches;
- a passed and human-reviewed shadow soak of at least 72 hours;
- a signed conformance bundle reference.

Even if all checks pass, `live_execution_allowed` remains `False`. This PR only
permits a human to discuss shadow-readiness of a Kamino combination after the
required evidence exists.

## Safety / non-goals

- No live trading is enabled.
- No liquidation transaction is built, signed or submitted.
- No sender API is modified.
- No Jupiter, MarginFi, Jito or RPC submission path is changed.
- No default Kamino market is marked verified.
- No official layout is guessed from placeholder bytes.

## Relationship to PR-050

PR-050 intentionally left Kamino fail-closed because the default registry is
empty and the reserve decoder is a small fixture decoder, not a production
layout. PR-067 keeps that behavior and adds the evidence gate needed before a
future PR can safely add real verified Kamino combinations.

## Focused verification

```bash
python -m pytest tests/lending/test_kamino_pr067_conformance.py -q
python -m compileall -q src/lending tests/lending/test_kamino_pr067_conformance.py
```

Full repository verification remains:

```bash
python scripts/verify_repo.py --skip-dependency-audit
```
