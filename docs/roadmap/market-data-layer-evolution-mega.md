# MEGA — Market Data Layer Evolution closure

## Purpose

This MEGA PR closes the implementable contract/research delta from
`MARKET_DATA_LAYER_EVOLUTION_RU_2026-09-20` without duplicating the already
merged PR-354 mechanism-discovery program.

The source plan was explicitly design-only.  Current-main reconciliation found
that many foundations already exist, so this PR is a bridge/closure layer, not a
second runtime:

- GitHub #496 / AGG-02 owns causal raw/PIT observations, durable journal, as-of
  state materialization and analytical replay.
- GitHub #500 / AGG-10 owns statistical relations, equal-budget ablation,
  feature research, model registry, regime memory, drift and
  champion/challenger logic.
- GitHub #521 / MEGA8-03 owns survival/UQ/causal/model-governance research.
- GitHub #533 / roadmap PR-354 fully owns RND-00..RND-11 and NF-1089..1184.
- GitHub #535 / roadmap PR-355 corrective completion owns the unified research
  protocol and mechanism-transfer/MarketPack bridge.
- Existing `src.inventory.research` remains the non-atomic
  futures/options/RWA/commodity rights and risk owner.

## What was actually missing

The repository did not contain concrete FRED/ALFRED, CFTC, PAXG/XAUT, CME/LBMA,
Deribit, TimesFM or Chronos integrations.  The PR-355 owner map mentioned gold
and macro MarketPacks, but only through a generic adapter owner.  Therefore it
would be incorrect to claim the Market Data Layer Evolution document was
already implemented.

This PR adds only the missing shared contracts and concrete default-off views:

- L0: `SourceManifest` + `InstrumentIdentity`;
- L1: `RawObservation` + `GapEvent`;
- L2: `NormalizedObservation` + strict `select_as_of`;
- L3: deterministic `StateSnapshot` + `ReplayManifest`;
- L4: `MarketEpisode` + non-executable `PredictiveRelation`;
- L5: cutoff/calibration-bound `ForecastRecord`;
- L6: fail-closed `QualificationEvidence`;
- L7: explicit research/effect boundary over existing inventory owners;
- L8: `ModelCandidate` + old-regime retention/rollback report.

Three concrete MarketPacks are added, all `DISABLED` and
`BLOCKED_EXTERNAL`:

1. MDE-P01 Crypto Derivatives and Basis;
2. MDE-P02 Gold Underlying and Claims;
3. MDE-P03 Macro Vintage and Cross Asset Regimes.

## Experiment closure

E01..E08 are preregistered in `config/market_data_evolution.json`.
Implementation of a contract does not mean an empirical result exists.
E03/E04/E05 remain externally blocked; no historical market data is fabricated.

The evaluation contract preserves the plan's six baselines, ten required metric
families, five temporal/OOS split requirements and seven forbidden leakage or
PnL shortcuts.

## Milestones

- D01: implemented owner map.
- D02: **BLOCKED_EXTERNAL** — real two-venue+lender+futures capture was not run.
- D03: episode/label contract implemented.
- D04: benchmark/ablation protocol implemented; empirical campaign not run.
- D05: gold research view implemented as a disabled contract; external
  data/licence/access remain blocked.
- D06: reuses AGG-10/PR-355 transfer and regime memory.
- D07: reuses research-only agent/evidence boundaries; no locked holdout access
  is granted.
- D08: execution remains separately owned and `live_enabled=false`.

## Source ledger

S01..S23 are recorded exactly as reference sources from the supplied design.
This PR performs no external data download and does not upgrade the document's
2026-09-20 source notes into current licence/entitlement attestations.
Every entry is `REFERENCE_ONLY / REVERIFY` until independently materialized.

## Safety and non-claims

This PR does not:

- add a provider/network client;
- copy external code, model weights or datasets;
- grant trading access from data access;
- create a second graph/model registry/financial ledger;
- load keys, sign, submit, fund, mutate remote resources or enable live;
- convert correlation into causality or an executable edge;
- treat mark prices as fills;
- treat synthetic PnL as real PnL;
- claim profitability, prediction accuracy, production readiness or external
  qualification.

## Rollback

Config-first: stop consuming MDE views/packs.  Existing AGG-02, AGG-10,
inventory, PR-354 and PR-355 owners remain canonical and intact.  Preserve
append-only research/evidence records.

## Verification

```bash
python scripts/verify_market_data_evolution.py --json
python -m pytest -q tests/market_data_evolution/test_market_data_evolution.py
python scripts/verify_pr354_mechanism_discovery.py --json
python scripts/verify_pr355.py --json
python scripts/verify_repo.py
```

Merge means the design's code/research contract layer is represented and
testable. It does not mean D02/D05 external data campaigns or any live execution
have occurred.
