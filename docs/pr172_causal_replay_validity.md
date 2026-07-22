# PR-172 causal replay, backtest and model-promotion validity gate

This PR adds the first safe, additive contract for roadmap **PR-172 —
Causal replay, backtest and model-promotion validity**.

The uploaded audit reproduced three risk classes that can produce false research
or promotion evidence:

1. feature history can learn from a terminal event that was not available at
   candidate time;
2. model evaluation can change when process environment changes;
3. backtest replay can open the wrong database/table and use float/linear
   economics while presenting the result as tuning evidence.

This slice is deliberately side-effect-free. It does not train a model, mutate
the active dataset builder, open SQLite, or promote any decision artifact. It
creates the contract that later integration work can feed from the active
dataset, backtest and model code.

## Added module

`src/causal_replay_pr172.py`

The module defines:

- `ReplayEvent` with explicit `observed_at_ns` and `available_at_ns`;
- `ReplayCorpusManifest` with dataset/code/policy hashes and replay tier;
- `EvaluationSplitEvidence` for train/calibration/test isolation;
- `BacktestInputContract` for strict table/path/schema/integer-money replay;
- `build_causal_feature_rows(...)`;
- `detect_temporal_leakage(...)`;
- `evaluate_replay_validity(...)`;
- `assert_no_model_promotion(...)`.

## Safety contract

The evaluator blocks promotion when:

- a feature row uses terminal history unavailable at candidate time;
- train/calibration/test partitions overlap;
- train statistics use non-train data;
- offline evaluation depends on live environment variables;
- a backtest opens a different DB from the requested DB;
- arbitrary SQLite table fallback is used;
- float money is used for financial replay;
- a linear haircut claims to be market replay;
- a synthetic corpus is used as promotion evidence without explicit allowance.

Decision replay may become reviewable, but still emits a warning that it is not
market replay.

## What this does not do

- No live trading.
- No provider/RPC/Jito/MarginFi/Jupiter network call.
- No signer/sender path.
- No active ranking enablement.
- No runtime environment flag changes.
- No claim that current backtest/model reports are already valid.
- No mutation of high-churn files such as `scripts/verify_repo.py` or
  `config/format_targets.txt`.

## Follow-up integration

A later PR-172 implementation should wire this gate to the active code paths:

- `src/decision/dataset.py` should build features strictly by event
  availability time and update history only when terminal events become
  available.
- `src/decision/model.py` should train intercept/statistics from train rows
  only, use the calibration partition, and evaluate independently of
  `DECISION_MODEL_ENABLED`.
- `scripts/backtest_replay.py` should become strict read-only replay over a
  single approved schema, with no path/table fallback and no float money.
- Promotion reports should include replay tier, uncertainty, calibration and
  immutable corpus/config/code identities.

## Suggested focused verification

```bash
python -m pytest tests/test_pr172_causal_replay_validity.py -q
python -m py_compile src/causal_replay_pr172.py tests/test_pr172_causal_replay_validity.py
```
