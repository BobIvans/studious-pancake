from __future__ import annotations

from dataclasses import replace

import pytest

from src.causal_replay_pr172 import (
    BacktestInputContract,
    EventType,
    EvaluationSplitEvidence,
    ReplayCorpusManifest,
    ReplayEvent,
    ReplayTier,
    assert_no_model_promotion,
    build_causal_feature_rows,
    detect_temporal_leakage,
    evaluate_replay_validity,
)


HASH = "a" * 64


def event(
    event_id: str,
    event_type: EventType,
    root: str,
    available: int,
    *,
    label: int | None = None,
    attempt: int = 1,
    evidence: int = 1,
) -> ReplayEvent:
    return ReplayEvent(
        event_id=event_id,
        event_type=event_type,
        root_opportunity_id=root,
        attempt_generation=attempt,
        evidence_generation=evidence,
        observed_at_ns=available,
        available_at_ns=available,
        provider_health="healthy",
        route_shape_class="stable",
        label_value=label,
    )


def good_manifest() -> ReplayCorpusManifest:
    return ReplayCorpusManifest(
        dataset_id="dataset:pr172",
        dataset_hash=HASH,
        code_hash=HASH,
        policy_bundle_hash=HASH,
        replay_tier=ReplayTier.DECISION_REPLAY,
        event_count=3,
    )


def good_split() -> EvaluationSplitEvidence:
    return EvaluationSplitEvidence(
        train_ids=("train-1",),
        calibration_ids=("cal-1",),
        test_ids=("test-1",),
        train_statistics_source="train-only",
        threshold_source="calibration",
    )


def good_backtest() -> BacktestInputContract:
    return BacktestInputContract(
        requested_db_path="/evidence/paper.db",
        opened_db_path="/evidence/paper.db",
        approved_table="paper_trades",
        observed_tables=("paper_trades",),
        schema_hash=HASH,
        read_only=True,
        used_float_money=False,
        arbitrary_table_fallback=False,
        linear_slippage_claims_market_replay=False,
    )


def test_causal_history_does_not_learn_future_terminal() -> None:
    events = [
        event("candidate-A", EventType.CANDIDATE, "root-A", 0),
        event("candidate-B", EventType.CANDIDATE, "root-B", 5),
        event("terminal-A", EventType.TERMINAL, "root-A", 20, label=1),
    ]

    rows = build_causal_feature_rows(events, label_horizon_ns=100)

    assert rows[0].candidate_event_id == "candidate-A"
    assert rows[0].historical_success_rate_ppm == 0
    assert rows[0].label_value == 1
    assert rows[1].candidate_event_id == "candidate-B"
    assert rows[1].historical_success_rate_ppm == 0
    assert rows[1].label_value is None


def test_temporal_leakage_detector_blocks_impossible_history() -> None:
    events = [
        event("candidate-B", EventType.CANDIDATE, "root-B", 5),
        event("terminal-A", EventType.TERMINAL, "root-A", 20, label=1),
    ]
    rows = build_causal_feature_rows(events, label_horizon_ns=100)
    bad_row = replace(rows[0], historical_success_count=1)

    blockers = detect_temporal_leakage(events, (bad_row,))

    assert blockers == (f"temporal_leakage:{bad_row.row_id}",)


def test_label_binds_attempt_and_evidence_generation() -> None:
    events = [
        event("candidate-A", EventType.CANDIDATE, "root-A", 0, attempt=2, evidence=7),
        event(
            "terminal-wrong-attempt",
            EventType.TERMINAL,
            "root-A",
            10,
            label=1,
            attempt=1,
            evidence=7,
        ),
        event("terminal-A", EventType.TERMINAL, "root-A", 20, label=0, attempt=2, evidence=7),
    ]

    rows = build_causal_feature_rows(events, label_horizon_ns=100)

    assert rows[0].terminal_event_id == "terminal-A"
    assert rows[0].label_value == 0


def test_manifest_rejects_synthetic_corpus_for_promotion() -> None:
    manifest = ReplayCorpusManifest(
        dataset_id="dataset:synthetic",
        dataset_hash=HASH,
        code_hash=HASH,
        policy_bundle_hash=HASH,
        replay_tier=ReplayTier.DECISION_REPLAY,
        event_count=3,
        synthetic=True,
    )
    report = evaluate_replay_validity(
        manifest=manifest,
        split=good_split(),
        backtest=good_backtest(),
        events=[
            event("candidate-A", EventType.CANDIDATE, "root-A", 0),
            event("terminal-A", EventType.TERMINAL, "root-A", 10, label=1),
        ],
    )

    assert report.promotion_allowed is False
    assert "manifest:synthetic_corpus_not_allowed_for_promotion" in report.blockers


def test_split_rejects_test_distribution_leakage() -> None:
    split = EvaluationSplitEvidence(
        train_ids=("row-1", "row-2"),
        calibration_ids=("row-2",),
        test_ids=("row-3",),
        train_statistics_source="all-labeled",
        threshold_source="hardcoded",
    )

    with pytest.raises(ValueError):
        split.validate()


def test_offline_evaluation_rejects_environment_dependent_behavior() -> None:
    split = EvaluationSplitEvidence(
        train_ids=("train-1",),
        calibration_ids=("cal-1",),
        test_ids=("test-1",),
        train_statistics_source="train-only",
        threshold_source="calibration",
        environment_dependent=True,
    )

    with pytest.raises(ValueError, match="environment"):
        split.validate()


def test_backtest_contract_rejects_arbitrary_table_fallback() -> None:
    contract = BacktestInputContract(
        requested_db_path="/requested.db",
        opened_db_path="/requested.db",
        approved_table="paper_trades",
        observed_tables=("paper_trades", "event_log"),
        schema_hash=HASH,
        read_only=True,
        used_float_money=False,
        arbitrary_table_fallback=True,
        linear_slippage_claims_market_replay=False,
    )

    with pytest.raises(ValueError, match="arbitrary SQLite tables"):
        contract.validate()


def test_backtest_contract_rejects_path_substitution_and_float_money() -> None:
    contract = BacktestInputContract(
        requested_db_path="/requested.db",
        opened_db_path="/paper_trading.db",
        approved_table="paper_trades",
        observed_tables=("paper_trades",),
        schema_hash=HASH,
        read_only=True,
        used_float_money=True,
        arbitrary_table_fallback=False,
        linear_slippage_claims_market_replay=False,
    )

    with pytest.raises(ValueError, match="different database"):
        contract.validate()


def test_complete_package_is_reviewable_but_decision_replay_warns() -> None:
    events = [
        event("candidate-A", EventType.CANDIDATE, "root-A", 0),
        event("terminal-A", EventType.TERMINAL, "root-A", 10, label=1),
    ]

    report = evaluate_replay_validity(
        manifest=good_manifest(),
        split=good_split(),
        backtest=good_backtest(),
        events=events,
    )

    assert report.promotion_allowed is True
    assert report.causal is True
    assert report.warnings == ("decision_replay_is_not_market_replay",)
    assert len(report.report_hash) == 64
    assert_no_model_promotion(report)


def test_promotion_assertion_fails_closed_on_blockers() -> None:
    bad_backtest = BacktestInputContract(
        requested_db_path="/requested.db",
        opened_db_path="/paper_trading.db",
        approved_table="paper_trades",
        observed_tables=("paper_trades",),
        schema_hash=HASH,
        read_only=True,
        used_float_money=False,
        arbitrary_table_fallback=False,
        linear_slippage_claims_market_replay=False,
    )
    report = evaluate_replay_validity(
        manifest=good_manifest(),
        split=good_split(),
        backtest=bad_backtest,
        events=[
            event("candidate-A", EventType.CANDIDATE, "root-A", 0),
            event("terminal-A", EventType.TERMINAL, "root-A", 10, label=1),
        ],
    )

    with pytest.raises(ValueError, match="different database"):
        assert_no_model_promotion(report)


def test_replay_event_rejects_candidate_with_label() -> None:
    with pytest.raises(ValueError, match="candidate event"):
        event("candidate-A", EventType.CANDIDATE, "root-A", 0, label=1)
