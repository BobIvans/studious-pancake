from __future__ import annotations

from src.mega8_03.pr195_survival import (
    calibrate_duration_predictions,
    fit_kaplan_meier_survival,
    fit_parametric_edge_duration,
    handle_censored_opportunities,
)
from src.mega8_03.pr196_conformal import (
    compute_prediction_set,
    fit_conformal_latency_interval,
    fit_conformal_net_interval,
    gate_on_uncertainty_budget,
)
from src.mega8_03.pr197_causal import (
    build_causal_event_graph,
    estimate_transfer_entropy,
    promote_causal_feature,
    test_event_precedence_hypothesis as event_precedence_hypothesis,
)
from src.mega8_03.pr198_hawkes import (
    estimate_cross_venue_excitation,
    fit_hawkes_event_model,
    forecast_event_intensity,
    validate_intensity_gain,
)
from src.mega8_03.pr199_gnn import (
    compare_graph_baseline,
    encode_dynamic_market_graph,
    score_graph_state_transition,
    train_graph_anomaly_model,
)
from src.mega8_03.pr200_temporal import (
    benchmark_inference_latency,
    build_temporal_sequence_dataset,
    score_sequence_survival,
    train_temporal_anomaly_model,
)
from src.mega8_03.pr201_active_learning import (
    measure_label_efficiency,
    request_targeted_labels,
    select_uncertain_samples,
    update_active_learning_pool,
)
from src.mega8_03.pr202_meta import (
    adapt_model_to_new_venue,
    learn_cross_market_representation,
    measure_transfer_gain,
    prevent_negative_transfer,
)
from src.mega8_03.pr203_model_robustness import (
    detect_distribution_attack,
    generate_adversarial_features,
    quarantine_unsafe_model,
    test_model_data_poisoning as model_data_poisoning,
)
from src.mega8_03.pr204_explanations import (
    audit_explanation_stability,
    compute_local_feature_attribution,
    emit_human_reason_code,
    trace_model_to_evidence,
)
from src.mega8_03.pr205_ope import (
    compute_importance_weights,
    estimate_offline_policy_value,
    reject_unsupported_policy_shift,
    run_doubly_robust_estimator,
)
from src.mega8_03.pr206_bandit import (
    apply_conservative_exploration,
    audit_bandit_regret_and_cost,
    define_safe_bandit_actions,
    select_simulation_budget_action,
)
from src.mega8_03.pr207_digital_twin import (
    calibrate_digital_twin,
    generate_synthetic_market_scenario,
    label_synthetic_vs_observed,
    validate_sim_to_real_gap,
)
from src.mega8_03.pr208_competition import (
    adjust_candidate_for_competition,
    cluster_competitor_archetypes,
    estimate_crowding_regime,
    model_alpha_capacity_decay,
)


def assert_advisory(model) -> None:
    assert model.execution_authority is False


def test_pr195_survival_preserves_censoring() -> None:
    km = fit_kaplan_meier_survival((10, 20, 30), (True, False, True))
    parametric = fit_parametric_edge_duration((10, 20, 30), (True, False, True))
    summary = handle_censored_opportunities(
        (
            {"duration_ns": 10, "event_observed": True},
            {"duration_ns": 20, "event_observed": False},
        )
    )
    calibration = calibrate_duration_predictions((10, 30), (12, 20), (False, True))
    assert km.parameters["censored_count"] == 1
    assert parametric.parameters["event_count"] == 2
    assert summary["right_censored_count"] == 1
    assert calibration["uncensored_mae_ns"] == 2
    assert_advisory(km)
    assert_advisory(parametric)


def test_pr196_conformal_bounds_are_explicit_admission_inputs() -> None:
    net = fit_conformal_net_interval((1, -2, 3, -4), miscoverage_ppm=250_000)
    latency = fit_conformal_latency_interval((10, 20, 30, 40), miscoverage_ppm=250_000)
    net_interval = compute_prediction_set(
        point_estimate=10, radius=net["radius_atomic"]
    )
    latency_interval = compute_prediction_set(
        point_estimate=100,
        radius=latency["radius_ns"],
        lower_floor=0,
    )
    gate = gate_on_uncertainty_budget(
        conservative_net_interval=net_interval,
        latency_interval_ns=latency_interval,
        minimum_net_atomic=0,
        maximum_latency_ns=1_000,
    )
    assert net_interval[0] > 0
    assert gate["admitted_offline"] is True


def test_pr196_conformal_uses_finite_sample_rank() -> None:
    net = fit_conformal_net_interval((1, 2, 3, 4), miscoverage_ppm=250_000)
    latency = fit_conformal_latency_interval((10, 20, 30, 40), miscoverage_ppm=250_000)
    assert net["radius_atomic"] == 4
    assert latency["radius_ns"] == 40


def test_pr197_causal_outputs_never_claim_causal_truth() -> None:
    graph = build_causal_event_graph(
        (
            {"event_id": "a", "event_type": "swap", "available_at_ns": 1},
            {"event_id": "b", "event_type": "liq", "available_at_ns": 2},
        ),
        maximum_lag_ns=5,
    )
    transfer = estimate_transfer_entropy(
        (0, 0, 1, 1, 0, 1),
        (0, 0, 0, 1, 1, 0),
    )
    precedence = event_precedence_hypothesis((1, 10), (2, 11), maximum_lag_ns=2)
    model = promote_causal_feature(
        feature_id="swap-to-liq",
        preregistered=True,
        holdout_gain_ppm=20_000,
        minimum_gain_ppm=10_000,
        stable_across_replays=True,
    )
    assert graph["precedence_edges"] == (("a", "b", 1),)
    assert transfer["sample_count"] == 5
    assert precedence["precedence_share_ppm"] == 1_000_000
    assert model.parameters["causal_truth_claimed"] is False
    assert_advisory(model)


def test_pr197_causal_graph_sorts_by_available_time_not_event_id() -> None:
    graph = build_causal_event_graph(
        (
            {"event_id": "a", "event_type": "later", "available_at_ns": 2},
            {"event_id": "b", "event_type": "earlier", "available_at_ns": 1},
        ),
        maximum_lag_ns=5,
    )
    assert graph["nodes"] == ("b", "a")
    assert graph["precedence_edges"] == (("b", "a", 1),)


def test_pr198_event_intensity_requires_holdout_gain() -> None:
    model = fit_hawkes_event_model(
        (10, 20, 40, 80),
        observation_horizon_ns=100,
    )
    excitation = estimate_cross_venue_excitation((10, 50), (11, 90), window_ns=5)
    forecast = forecast_event_intensity(model, elapsed_since_last_event_ns=5)
    gain = validate_intensity_gain(
        model_log_loss_ppm=800,
        baseline_log_loss_ppm=1_000,
        minimum_gain_ppm=100_000,
    )
    assert excitation["excited_share_ppm"] == 500_000
    assert forecast["relative_intensity_ppm"] >= 1_000_000
    assert gain["holdout_gain_verified"] is True
    assert_advisory(model)


def test_pr199_graph_challenger_is_compared_to_deterministic_baseline() -> None:
    encoded = encode_dynamic_market_graph(
        ({"node_id": "a"}, {"node_id": "b"}),
        ({"source": "a", "target": "b", "weight_atomic": 10},),
    )
    model = train_graph_anomaly_model((encoded, tuple(value + 1 for value in encoded)))
    score = score_graph_state_transition(model, encoded)
    comparison = compare_graph_baseline(
        challenger_scores=(0, 100),
        baseline_scores=(40, 50),
        labels=(0, 1),
    )
    assert score >= 0
    assert comparison["challenger_beats_baseline"] is True
    assert_advisory(model)


def test_pr200_temporal_dataset_is_available_time_ordered() -> None:
    dataset = build_temporal_sequence_dataset(
        (
            {"available_at_ns": 3, "features": (3, 30)},
            {"available_at_ns": 1, "features": (1, 10)},
            {"available_at_ns": 2, "features": (2, 20)},
        ),
        window=2,
    )
    model = train_temporal_anomaly_model(dataset)
    score = score_sequence_survival(model, dataset[0])
    bench = benchmark_inference_latency((10, 20, 30, 40), maximum_p95_ns=50)
    assert dataset[0][0] == (1, 10)
    assert 0 <= score <= 1_000_000
    assert bench["within_latency_budget"] is True
    assert_advisory(model)


def test_pr201_active_learning_consumes_only_bounded_label_quota() -> None:
    selected = select_uncertain_samples(
        (
            {"sample_id": "a", "probability_ppm": 490_000},
            {"sample_id": "b", "probability_ppm": 900_000},
        ),
        limit=2,
    )
    requests = request_targeted_labels(selected, quota_units=3, cost_per_label=2)
    pool = update_active_learning_pool({"a": None, "b": None}, {"a": "positive"})
    efficiency = measure_label_efficiency((100, 100), (60, 80), acquired_labels=1)
    assert selected[0]["sample_id"] == "a"
    assert len(requests) == 1
    assert pool["a"] == "positive"
    assert efficiency["uncertainty_reduction_ppm"] == 30


def test_pr202_meta_learning_blocks_negative_transfer() -> None:
    source = learn_cross_market_representation(((1, 2), (3, 4)))
    adapted = adapt_model_to_new_venue(source, ((2, 3), (4, 5)))
    gain = measure_transfer_gain(baseline_loss_ppm=1_000, transferred_loss_ppm=800)
    allowed = prevent_negative_transfer(
        transfer_gain_ppm=gain, minimum_gain_ppm=100_000
    )
    denied = prevent_negative_transfer(transfer_gain_ppm=-1, minimum_gain_ppm=0)
    assert allowed["transfer_allowed"] is True
    assert denied["transfer_allowed"] is False
    assert_advisory(source)
    assert_advisory(adapted)


def test_pr203_model_robustness_can_quarantine() -> None:
    down, up = generate_adversarial_features({"x": 100}, perturbation_ppm=100_000)
    poison = model_data_poisoning((100, 100), (200, 100))
    drift = detect_distribution_attack((100, 100), (200, 200))
    quarantine = quarantine_unsafe_model(
        poisoning_shift_ppm=poison["max_score_shift_ppm"],
        distribution_shift_ppm=drift["mean_shift_ppm"],
        maximum_poisoning_shift_ppm=50,
        maximum_distribution_shift_ppm=500_000,
    )
    assert down["x"] == 90
    assert up["x"] == 110
    assert quarantine["quarantined"] is True
    assert quarantine["execution_authority"] is False


def test_pr204_explanations_are_bound_to_evidence() -> None:
    attribution = compute_local_feature_attribution(
        {"x": 500_000, "y": -250_000}, {"x": 4, "y": 8}
    )
    reasons = emit_human_reason_code(attribution)
    trace = trace_model_to_evidence(("x", "y"), {"x": "a" * 64, "y": "b" * 64})
    stability = audit_explanation_stability(
        (attribution, dict(attribution)), maximum_mean_delta=0
    )
    assert reasons
    assert trace["x"] == "a" * 64
    assert stability["stable"] is True


def test_pr205_ope_checks_support_instead_of_treating_shadow_as_landed() -> None:
    weights = compute_importance_weights(
        (500_000, 500_000),
        (500_000, 250_000),
        maximum_weight_ppm=2_000_000,
    )
    ips = estimate_offline_policy_value((10, 20), weights)
    dr = run_doubly_robust_estimator((10, 20), (8, 18), (9, 19), weights)
    support = reject_unsupported_policy_shift(
        weights,
        maximum_weight_ppm=2_000_000,
        minimum_effective_sample_ppm=100_000,
    )
    assert weights == (1_000_000, 500_000)
    assert ips == 10
    assert dr >= 0
    assert support["supported"] is True


def test_pr205_ope_preserves_weight_overflow_for_support_rejection() -> None:
    weights = compute_importance_weights(
        (1, 1),
        (1_000_000, 1_000_000),
        maximum_weight_ppm=2_000_000,
    )
    support = reject_unsupported_policy_shift(
        weights,
        maximum_weight_ppm=2_000_000,
        minimum_effective_sample_ppm=100_000,
    )
    assert weights == (2_000_001, 2_000_001)
    assert support["supported"] is False


def test_pr206_bandit_has_no_live_actions_and_audits_cost() -> None:
    actions = define_safe_bandit_actions(
        (
            {
                "action_id": "simulate-a",
                "cost_units": 1,
                "information_gain_ppm": 100,
                "uncertainty_reduction_ppm": 100,
                "live_effect": False,
            },
            {
                "action_id": "live-a",
                "cost_units": 1,
                "information_gain_ppm": 1_000,
                "uncertainty_reduction_ppm": 1_000,
                "live_effect": True,
            },
        ),
        hard_quota_units=5,
    )
    selected = select_simulation_budget_action(actions)
    chosen = apply_conservative_exploration(
        selected_action=selected,
        baseline_action=actions[0],
        exploration_budget_ppm=100_000,
        deterministic_draw_ppm=50_000,
    )
    audit = audit_bandit_regret_and_cost((8, 9), (10, 10), (1, 1))
    assert len(actions) == 1
    assert chosen["live_effect"] is False
    assert audit["cumulative_regret_atomic"] == 3


def test_pr207_synthetic_twin_cannot_enter_realized_pnl() -> None:
    scenario = generate_synthetic_market_scenario(
        {"price": 100}, {"price": -10}, scenario_id="s1"
    )
    calibration = calibrate_digital_twin((100, 105), (100, 100))
    verdict = validate_sim_to_real_gap(calibration, maximum_gap_ppm=100_000)
    labels = label_synthetic_vs_observed(
        (
            {"episode_id": "s", "source_kind": "synthetic"},
            {"episode_id": "o", "source_kind": "observed"},
        )
    )
    assert scenario["synthetic"] is True
    assert scenario["realized_pnl_eligible"] is False
    assert verdict["calibrated_for_research"] is True
    assert labels[0]["realized_pnl_eligible"] is False
    assert labels[1]["realized_pnl_eligible"] is True


def test_pr208_competition_adjustment_only_reduces_candidate() -> None:
    clusters = cluster_competitor_archetypes(
        (
            {
                "public_actor_id": "a",
                "latency_ms": 50,
                "typical_size_atomic": 2_000,
            },
            {
                "public_actor_id": "b",
                "latency_ms": 200,
                "typical_size_atomic": 10,
            },
        )
    )
    regime = estimate_crowding_regime(
        competitor_count=2,
        attempts_per_episode_ppm=400_000,
        landed_share_ppm=300_000,
    )
    decay = model_alpha_capacity_decay((10, 20, 30), (5, 1, -1))
    adjusted = adjust_candidate_for_competition(
        conservative_net_atomic=100,
        crowding_penalty_ppm=100_000,
        decay_penalty_ppm=200_000,
    )
    assert len(clusters) == 2
    assert regime["regime"] in {"low", "medium", "high"}
    assert decay["largest_positive_size_atomic"] == 20
    assert adjusted["adjusted_net_atomic"] == 70
    assert adjusted["execution_authority"] is False
