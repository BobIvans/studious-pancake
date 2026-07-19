# PR-022 offline decision intelligence

PR-022 adds a shadow-only, offline decision-intelligence package. Its target is
`P(simulated_executable_profit | PRE_QUOTE information)`: positive labels require
PR-013 terminal shadow simulation success, complete reconciliation, proven
repayment, PR-010 post-simulation pass, and simulated executable net PnL above a
canonical base-unit threshold. Attempted terminal outcomes that do not satisfy all
positive predicates are negative. Missing/corrupt/outstanding outcomes inside the
UTC label horizon are censored and excluded.

## Feature and leakage contract

Rows have `features_pre_quote`, `labels_only`, and `audit_only` namespaces. The
implemented pre-quote allowlist is versioned in `src/decision/contracts.py` and
contains only categorical strategy/market/route/provider/capacity features,
candidate/slot age integers, and rolling historical ppm aggregates computed from
strictly earlier terminal events. Forbidden pre-quote data includes final quote,
raw route, simulation diagnostics, terminal reason/logs, balances, repayment,
PnL, sends/landings, secrets, `uiAmount`, float SOL money, and legacy score.

## Split and calibration policy

`PurgedGroupedTimeSplit` creates chronological train -> calibration -> test
partitions. All rows sharing a lineage/root group remain on exactly one side, and
an embargo prevents label-horizon freshness/replay leakage. Imputation/category
vocabulary/scaling are fitted from training rows only by the JSON linear trainer.
The scikit-learn dependency is pinned at `scikit-learn==1.8.0`; its calibration,
`CalibratedClassifierCV`, reliability curve, and permutation-importance docs are
referenced in `docs/external_contracts.yaml`, but PR-022 uses explicit temporal
splits and a safe JSON model artifact rather than executable pickle/joblib.

## Baseline, model, artifacts, and quality gates

The baseline is deterministic and explainable: fresh, healthy, quota-available,
cheap-capacity-pass candidates rank above stale/degraded/denied candidates. The
initial challenger is a small deterministic logistic/linear classifier exported
as canonical JSON containing schema/order/categories, normalization parameters,
coefficients/intercept, split manifest, dependency versions, checksum, and class
counts. Too-small data, one-class data, invalid artifact checksums, dependency or
schema mismatch, failed quality gates, or `DECISION_MODEL_ENABLED=false` returns
`MODEL_DISABLED` or `DISABLED_INSUFFICIENT_DATA` and baseline-only ranking.
Artifacts are advisory only; human review is required before registering any
quota-influencing mode. There is no online learning, automatic promotion, sender,
Jito, RPC, permit, risk-policy, provider-role, or config mutation path.

## Quota and shadow integration

`RankingRecommendation` returns artifact version/checksum, PRE_QUOTE stage,
optional calibrated probability, baseline priority, advisory band, explanations,
and model status. The strategy queue consumes the recommendation in shadow mode
without changing ordering; approved advisory mode may rank only candidates that
already passed cheap deterministic gates. Provider rate limits and Jupiter final
build policy are preserved outside the model. Quota replay reserves a deterministic
exploration share so low-score/new categories continue collecting labels.

## Reports and drift

Evaluation reports include class coverage, Brier/log-loss placeholders for tiny
fixtures, PR/ROC availability, reliability/ECE, baseline-vs-model top-k utility,
prediction distribution, feature-missingness/drift status, split manifest, artifact
checksum, and as-of time. Drift metrics are offline only and never emit external
alerts or alter live controls.
