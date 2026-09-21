from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_pr357 import verify
from src.research.pr357_contracts import (
    CONTRACT_SCHEMAS,
    PR357ContractError,
    contract_type,
)
from src.research.pr357_core import (
    InformationActionSpec,
    LifecycleState,
    ObservationClock,
    apply_lifecycle_hysteresis,
    compute_evidence_age_vector,
    define_market_belief_state,
    detect_double_counted_information,
    estimate_evsi,
    generate_joint_predictive_distribution,
    record_lifecycle_transition,
    replay_lifecycle_history,
    reserve_safety_information_budget,
    widen_uncertainty_under_missingness,
)
from src.research.pr357_integrated import run_pr357_integrated_vertical

ROOT = Path(__file__).resolve().parents[2]


def test_owner_map_covers_all_384_exact_requirements() -> None:
    payload = json.loads(
        (ROOT / "config/pr357_owner_map.json").read_text(encoding="utf-8")
    )
    rows = payload["requirements"]
    assert len(rows) == 384
    assert len({row["id"] for row in rows}) == 384
    assert len({row["symbol"] for row in rows}) == 384
    assert payload["counts"]["not_run"] == 0
    assert payload["duplicate_authorities"] == []
    assert not any(payload["effect_boundary"].values())


def test_all_40_normative_contract_types_are_immutable_and_fail_closed() -> None:
    assert len(CONTRACT_SCHEMAS) == 40
    lifecycle = contract_type("StrategyLifecycleRecord")
    fields = CONTRACT_SCHEMAS["StrategyLifecycleRecord"]
    kwargs = {field: "fixture" for field in fields}
    kwargs["execution_right"] = True
    with pytest.raises(PR357ContractError):
        lifecycle(**kwargs)


def test_lifecycle_transition_is_append_only_and_replayable() -> None:
    first = record_lifecycle_transition(
        strategy_id="s1",
        previous_state=LifecycleState.RESEARCH_ONLY,
        next_state=LifecycleState.OBSERVING,
        decision_time=10,
        reason="fixture",
        evidence_refs=("e1",),
    )
    second = record_lifecycle_transition(
        strategy_id="s1",
        previous_state=LifecycleState.OBSERVING,
        next_state=LifecycleState.REQUALIFICATION_DUE,
        decision_time=20,
        reason="stale evidence",
        evidence_refs=("e2",),
    )
    assert (
        replay_lifecycle_history(
            LifecycleState.RESEARCH_ONLY,
            (first, second),
            15,
        )
        is LifecycleState.OBSERVING
    )
    assert (
        replay_lifecycle_history(
            LifecycleState.RESEARCH_ONLY,
            (first, second),
            25,
        )
        is LifecycleState.REQUALIFICATION_DUE
    )
    assert first.receipt_hash != second.receipt_hash
    assert first.execution_right is False


def test_multidimensional_evidence_age_detects_hard_invalidator() -> None:
    age = compute_evidence_age_vector(
        now=100,
        evidence_available_at=50,
        current_deployment_generation=3,
        evidence_deployment_generation=2,
        current_source_schema_generation=4,
        evidence_source_schema_generation=4,
        current_topology_generation=5,
        evidence_topology_generation=5,
        regime_distance=10,
        current_model_generation=6,
        evidence_model_generation=6,
    )
    assert "DEPLOYMENT_GENERATION_CHANGED" in age.hard_invalidators


def test_lifecycle_hysteresis_requires_stronger_reverse_evidence() -> None:
    assert (
        apply_lifecycle_hysteresis(
            forward_score=90,
            reverse_score=95,
            forward_threshold=80,
            reverse_threshold=100,
        )
        == "FORWARD"
    )
    assert (
        apply_lifecycle_hysteresis(
            forward_score=10,
            reverse_score=110,
            forward_threshold=80,
            reverse_threshold=100,
        )
        == "REVERSE"
    )


def test_pit_belief_rejects_future_observation() -> None:
    future = ObservationClock(1, 2, 3, 11, "s", "r")
    with pytest.raises(PR357ContractError):
        define_market_belief_state(
            belief_id="b",
            decision_time=10,
            observed={"x": 1},
            posterior_mean={"x": 1},
            covariance={"x": {"x": 4}},
            missingness_mask={"x": False},
            source_clocks={"x": future},
            valid_until=20,
        )


def test_missingness_widens_uncertainty_and_scenarios_replay() -> None:
    covariance = {
        "x": {"x": 4, "y": 1},
        "y": {"x": 1, "y": 9},
    }
    widened = widen_uncertainty_under_missingness(
        covariance,
        {"x": False, "y": True},
        factor_ppm=1_500_000,
    )
    assert widened["y"]["y"] > covariance["y"]["y"]
    clock = ObservationClock(1, 2, 3, 4, "s", "r")
    belief = define_market_belief_state(
        belief_id="b",
        decision_time=10,
        observed={"x": 1},
        posterior_mean={"x": 1, "y": 2},
        covariance=widened,
        missingness_mask={"x": False, "y": True},
        source_clocks={"x": clock},
        valid_until=20,
    )
    assert generate_joint_predictive_distribution(
        belief,
        sample_count=5,
        seed=357,
    ) == generate_joint_predictive_distribution(
        belief,
        sample_count=5,
        seed=357,
    )


def test_redundancy_and_common_safety_budget_are_fail_closed() -> None:
    assert detect_double_counted_information(
        ("a", "b"),
        {("a", "b"): 950_000},
        threshold_ppm=900_000,
    ) == (("a", "b"),)

    mandatory = InformationActionSpec("safety", 1, 2, 1, 10, True, "p0")
    optional = InformationActionSpec("optional", 10, 2, 1, 10, False, "p1")
    plan = reserve_safety_information_budget(
        (mandatory, optional),
        budget_units=2,
    )
    assert plan["selected"] == ("safety",)
    blocked = reserve_safety_information_budget(
        (mandatory, optional),
        budget_units=1,
    )
    assert blocked["status"] == "ABSTAIN"


def test_integrated_vertical_reduces_regret_and_never_authorizes_execution() -> None:
    first = run_pr357_integrated_vertical()
    second = run_pr357_integrated_vertical()
    assert first["integrated_receipt_hash"] == second["integrated_receipt_hash"]
    assert first["status"] == "SUPPORTED_RESEARCH_ONLY"
    assert (
        first["decision"]["challenger_regret_units"]
        < first["decision"]["baseline_regret_units"]
    )
    assert first["decision"]["absent_safety_probe"] == "ABSTAIN"
    assert first["execution_right"] is False
    assert first["production_ready"] is False
    assert first["live_enabled"] is False
    assert first["realized_pnl_claim"] is False
    assert not any(first["effect_boundary"].values())


def test_lifecycle_replay_preserves_append_order_for_equal_timestamps() -> None:
    first = record_lifecycle_transition(
        strategy_id="same-time",
        previous_state=LifecycleState.RESEARCH_ONLY,
        next_state=LifecycleState.OBSERVING,
        decision_time=10,
        reason="first append",
        evidence_refs=("e1",),
    )
    second = record_lifecycle_transition(
        strategy_id="same-time",
        previous_state=LifecycleState.OBSERVING,
        next_state=LifecycleState.REQUALIFICATION_DUE,
        decision_time=10,
        reason="second append",
        evidence_refs=("e2",),
    )
    assert (
        replay_lifecycle_history(
            LifecycleState.RESEARCH_ONLY,
            (first, second),
            10,
        )
        is LifecycleState.REQUALIFICATION_DUE
    )


def test_pit_belief_requires_clock_for_every_observed_variable() -> None:
    with pytest.raises(PR357ContractError, match="PR357_OBSERVED_CLOCK_MISSING:x"):
        define_market_belief_state(
            belief_id="missing-clock",
            decision_time=10,
            observed={"x": 1},
            posterior_mean={"x": 1},
            covariance={"x": {"x": 4}},
            missingness_mask={"x": False},
            source_clocks={},
            valid_until=20,
        )


def test_joint_scenarios_honor_positive_and_negative_covariance() -> None:
    clock = ObservationClock(1, 2, 3, 4, "s", "r")
    common = {
        "belief_id": "covariance",
        "decision_time": 10,
        "observed": {"x": 0, "y": 0},
        "posterior_mean": {"x": 0, "y": 0},
        "missingness_mask": {"x": False, "y": False},
        "source_clocks": {"x": clock, "y": clock},
        "valid_until": 20,
    }
    positive = define_market_belief_state(
        **common,
        covariance={
            "x": {"x": 100, "y": 80},
            "y": {"x": 80, "y": 100},
        },
    )
    negative = define_market_belief_state(
        **common,
        covariance={
            "x": {"x": 100, "y": -80},
            "y": {"x": -80, "y": 100},
        },
    )
    positive_samples = generate_joint_predictive_distribution(
        positive,
        sample_count=1_000,
        seed=357,
    )
    negative_samples = generate_joint_predictive_distribution(
        negative,
        sample_count=1_000,
        seed=357,
    )
    positive_cross = sum(row["x"] * row["y"] for row in positive_samples)
    negative_cross = sum(row["x"] * row["y"] for row in negative_samples)
    assert positive_cross > 0
    assert negative_cross < 0
    assert positive_samples != negative_samples


def test_evsi_rejects_posterior_mixture_that_does_not_reproduce_prior() -> None:
    decision = {
        "actions": {
            "A": {"down": 100, "up": 0},
            "B": {"down": 10, "up": 10},
        },
        "state_probabilities_ppm": {"down": 500_000, "up": 500_000},
        "deadline": 10,
        "mandatory_safety": (),
        "execution_right": False,
    }
    with pytest.raises(PR357ContractError, match="PR357_POSTERIOR_MIXTURE_INCOHERENT"):
        estimate_evsi(
            decision,
            posterior_scenarios=({"down": 0, "up": 1_000_000},),
            observation_probabilities_ppm=(1_000_000,),
        )

def test_full_pr357_verifier() -> None:
    result = verify()
    assert result["accepted"], result["errors"]
    assert result["requirements"] == 384
    assert result["packages"] == 48
    assert result["typed_contracts"] == 40
    assert result["hypotheses"] == 80
    assert result["challenges"] == 40
    assert result["execution_right"] is False
