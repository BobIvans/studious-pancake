# AGG-10 — measurable data utility and strategy learning

This change implements the AGG-10 research/intelligence layer as an additive,
default-off extension of the existing `src.decision` authority.

## Scope

The implementation covers MARKET-02, MEV-01, ML-01, ML-02 and ML-03 and maps
all 28 required NF identifiers to concrete code in `src/decision/agg10.py`.

The layer provides:

- available-at statistical relation graphs and equal-budget source ablation;
- permission-bound orderflow observations, router coverage hypotheses and
  oracle-divergence meta-signals;
- robust univariate/multivariate research features and bounded feature grammar;
- simulation-budget ranking, buildability abstention and exact-trace size
  proposals;
- censor-aware survival modelling and a fail-closed LIVE-03-only landing/cost
  model;
- factor/lead-lag research contracts, invariant monitoring, regime memory,
  deterministic drift checks and content-addressed model bundles;
- frozen-holdout champion/challenger promotion and value-of-information query
  selection that cannot drop mandatory safety checks;
- a counterfactual market-world layer, synthetic stress scenarios, alpha
  capacity/reflexivity evidence, typed symbolic strategy composition and
  bounded offline-policy evaluation;
- a task-scoped learning acceptance verdict with deterministic fallback and no
  live authority.

## Safety and authority boundary

AGG-10 is sender-free. It does not import or initialize a signer, sender, Jito
transport, RPC submission path or remote-resource mutator. Statistical and ML
outputs are advisory/research evidence only; hard admission, compiler,
firewall, financing, reservation and execution owners stay authoritative.

`NF-223` is deliberately blocked without actual sent-attempt evidence tied to a
LIVE-03 evidence identity. Paper and counterfactual rows cannot be converted
into positive or negative landing labels.

No model can change risk limits, create a trusted program/primitive, authorize
live execution, or trade away a mandatory safety query to save quota.

## Dependency disposition

Post-AGG reconciliation confirms merged receipts for AGG-02, AGG-04 and AGG-05,
so those package dependencies are no longer current blockers. AGG-10
implementation status is `MERGED_CODE`.

Operational status remains **UNQUALIFIED** where evidence is absent. In
particular NF-223 still requires actual sent-attempt landing/cost labels sourced
from LIVE-03 for the selected exact profile; the fact that AGG-08 code is merged
does not create those observations. Paper/counterfactual rows remain ineligible
as real landing labels.

## Verification

Focused tests in `tests/test_agg10_intelligence.py` exercise all five work
packages and the major negative cases, including temporal/authority boundaries,
censoring, LIVE-03 label admission, source-ablation comparability, drift,
model promotion, symbolic debt closure and offline-policy support.

Repository CI, package smoke and normal verification remain authoritative for
the merged tree. Passing this PR does not make live trading available.
