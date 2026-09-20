from __future__ import annotations

import pytest

from src.decision.agg10 import (
    AGG10_NF_COVERAGE,
    AblationArm,
    AdvancedModelExperiment,
    BudgetedSimulationRanker,
    BuildabilityModel,
    CandidateLearningRow,
    CapacityReflexivityReport,
    CoverageGapHypothesis,
    ExactSizeTrace,
    ExogenousScenario,
    FeatureDefinition,
    FeatureGenerator,
    FeatureTransform,
    FrozenExperiment,
    InvariantCheck,
    LabelState,
    LandingCostModel,
    LandingObservation,
    LearningTaskEvidence,
    MarketWorldModel,
    ModelBundle,
    ModelRegistry,
    MultivariateAnomalyModel,
    OfflinePolicyCandidate,
    OracleDivergenceSignal,
    OrderflowObservation,
    PromotionMetrics,
    QueryCandidate,
    RegimeMemory,
    RegimeModelSnapshot,
    SizeProposalModel,
    StatisticalRelationGraph,
    StrategyPrimitive,
    SurvivalModel,
    SurvivalObservation,
    SymbolicStrategyFactory,
    TimedFeatureRow,
    ValueOfInformationPolicy,
    compare_champion_challenger,
    compare_source_ablation,
    drift_monitor,
    evaluate_offline_policies,
    factor_cointegration_research,
    lead_lag_research,
    qualify_learning_layer,
    robust_statistics,
    run_stress_scenarios,
    validate_agg10_coverage,
)

pytestmark = pytest.mark.unit


def _experiment() -> FrozenExperiment:
    return FrozenExperiment("agg10-exp", "split-v1", "workload-v1", 100)


def test_all_28_nf_have_concrete_coverage() -> None:
    assert validate_agg10_coverage()
    assert len(AGG10_NF_COVERAGE) == 28


def test_experiment_is_frozen_holdout_and_sender_free() -> None:
    assert _experiment().live_effects_allowed is False
    with pytest.raises(ValueError, match="locked temporal holdout"):
        FrozenExperiment("x", "s", "w", 1, holdout_locked=False)
    with pytest.raises(ValueError, match="live effects"):
        FrozenExperiment("x", "s", "w", 1, live_effects_allowed=True)


def test_orderflow_requires_authorization_and_hint_cannot_claim_settlement() -> None:
    with pytest.raises(PermissionError):
        OrderflowObservation(
            "private", "1", "hint", 1.0, 2.0, False, "hash"
        )
    with pytest.raises(ValueError, match="hint cannot"):
        OrderflowObservation(
            "allowed", "1", "hint", 1.0, 2.0, True, "hash", True
        )
    observed = OrderflowObservation(
        "allowed", "2", "signed_order", 1.0, 2.0, True, "hash"
    )
    assert observed.full_transaction_observed


def test_statistical_relations_are_hypotheses_not_trade_permissions() -> None:
    rows = [
        TimedFeatureRow(
            str(i), float(i), {"a": float(i), "b": float(i + 1)}
        )
        for i in range(1, 8)
    ]
    edges = StatisticalRelationGraph.fit(
        rows, feature_pairs=(("a", "b"),), lags=(0, 1)
    )
    assert len(edges) == 2
    assert all(
        not edge.trade_permission and not edge.causal_claim
        for edge in edges
    )
    assert all(
        edge.corrected_alpha == pytest.approx(0.025)
        for edge in edges
    )


def test_source_ablation_requires_same_episodes_and_equal_budget() -> None:
    baseline = AblationArm(
        "local", ("e1", "e2"), 1, 2, 1, 10
    )
    challenger = AblationArm(
        "reference", ("e1", "e2"), 2, 2, 2, 20
    )
    report = compare_source_ablation(
        _experiment(), baseline, challenger
    )
    assert report.uplift_precision == pytest.approx(0.5)
    assert report.equal_workload and report.equal_budget
    with pytest.raises(ValueError, match="same independent episodes"):
        compare_source_ablation(
            _experiment(),
            baseline,
            AblationArm(
                "bad", ("e1", "e3"), 1, 2, 1, 10
            ),
        )


def test_coverage_gap_never_auto_trusts_new_program() -> None:
    hypothesis = CoverageGapHypothesis(
        "market", 100, "aggregator_omission", 110, 105, False
    )
    assert hypothesis.execution_proven is False
    with pytest.raises(ValueError, match="untrusted"):
        CoverageGapHypothesis(
            "market",
            100,
            "aggregator_omission",
            110,
            105,
            False,
            True,
        )


def test_oracle_divergence_is_feature_only() -> None:
    signal = OracleDivergenceSignal(
        "USDC",
        1.01,
        1.0,
        0.5,
        0.001,
        ("stable", "security"),
        True,
    )
    assert signal.relative_divergence == pytest.approx(0.01)
    with pytest.raises(ValueError, match="not a trading venue"):
        OracleDivergenceSignal(
            "USDC",
            1.01,
            1.0,
            0.5,
            0.001,
            ("stable",),
            True,
            True,
        )


def test_robust_statistics_handles_constant_variance_and_gaps() -> None:
    result = robust_statistics(
        [1.0, None, 1.0, 10.0], unit="bps"
    )
    assert result.window == 4
    assert result.missing_fraction == pytest.approx(0.25)
    constant = robust_statistics([3.0, 3.0, 3.0])
    assert constant.mad == 0
    assert constant.robust_z == 0


def test_multivariate_anomaly_model_handles_singular_columns() -> None:
    model = MultivariateAnomalyModel.fit(
        (
            {"x": 1.0, "y": 2.0},
            {"x": 1.0, "y": 3.0},
            {"x": 1.0, "y": 4.0},
        )
    )
    score = model.score({"x": 1.0, "y": 5.0})
    assert score > 0


def test_feature_generation_is_allowlisted_and_bounded() -> None:
    definitions = (
        FeatureDefinition(
            "price", FeatureTransform.IDENTITY, ("price",)
        ),
        FeatureDefinition(
            "lag_price",
            FeatureTransform.LAG,
            ("price",),
            window=1,
        ),
        FeatureDefinition(
            "spread_ratio",
            FeatureTransform.RATIO,
            ("ask", "bid"),
            cost_units=2,
        ),
    )
    generator = FeatureGenerator(
        definitions, budget_units=4
    )
    features = generator.materialize(
        (
            {"price": 10.0, "ask": 11.0, "bid": 10.0},
            {"price": 12.0, "ask": 13.0, "bid": 12.0},
        )
    )
    assert features["price"] == 12
    assert features["lag_price"] == 10
    assert features["spread_ratio"] == pytest.approx(13 / 12)
    with pytest.raises(ValueError, match="future labels"):
        FeatureDefinition(
            "future_label", FeatureTransform.IDENTITY, ("x",)
        )


def _learning_rows() -> tuple[CandidateLearningRow, ...]:
    return (
        CandidateLearningRow(
            "c1",
            "e1",
            {"age": 1.0, "depth": 9.0},
            True,
            True,
            True,
            adapter_id="a",
        ),
        CandidateLearningRow(
            "c2",
            "e2",
            {"age": 8.0, "depth": 2.0},
            True,
            False,
            False,
            "cu",
            "a",
        ),
        CandidateLearningRow(
            "c3",
            "e3",
            {"age": 2.0, "depth": 8.0},
            True,
            True,
            True,
            adapter_id="a",
        ),
        CandidateLearningRow(
            "c4",
            "e4",
            {"age": 7.0, "depth": 1.0},
            True,
            False,
            False,
            "accounts",
            "a",
        ),
        CandidateLearningRow(
            "c5",
            "e5",
            {"age": 3.0, "depth": 7.0},
            True,
            None,
            None,
            adapter_id="new",
        ),
        CandidateLearningRow(
            "c6",
            "e6",
            {"age": 0.0, "depth": 99.0},
            False,
            True,
            True,
            adapter_id="a",
        ),
    )


def test_simulation_ranker_only_ranks_admitted_and_logs_propensity() -> None:
    rows = _learning_rows()
    ranker = BudgetedSimulationRanker.fit(rows)
    ranked = ranker.rank(rows, budget=2)
    assert len(ranked) == 2
    assert all(
        item.candidate_id != "c6" for item in ranked
    )
    assert all(
        item.propensity == pytest.approx(2 / 5)
        for item in ranked
    )


def test_buildability_abstains_on_unseen_or_low_support_adapter() -> None:
    model = BuildabilityModel.fit(
        _learning_rows(), min_support=3
    )
    assert model.predict("a").abstained is False
    assert model.predict("new").abstained is True


def test_size_surrogate_proposes_only_exact_observed_feasible_sizes() -> None:
    model = SizeProposalModel(
        (
            ExactSizeTrace(10, 1, True),
            ExactSizeTrace(20, -1, True),
            ExactSizeTrace(30, 9, True),
            ExactSizeTrace(40, 100, False),
        )
    )
    assert model.propose(
        max_amount=35, top_k=2
    ) == (30, 10)


def test_survival_model_does_not_treat_censoring_as_negative() -> None:
    rows = (
        SurvivalObservation(
            "1", "arb", "calm", 500, LabelState.POSITIVE
        ),
        SurvivalObservation(
            "2", "arb", "calm", 500, LabelState.NEGATIVE
        ),
        SurvivalObservation(
            "3", "arb", "calm", 500, LabelState.CENSORED
        ),
        SurvivalObservation(
            "4", "arb", "calm", 500, LabelState.POSITIVE
        ),
    )
    prediction = SurvivalModel(
        rows, min_support=3
    ).predict(
        family="arb", regime="calm", horizon_ms=500
    )
    assert prediction.support == 3
    assert prediction.probability == pytest.approx(2 / 3)


def test_landing_model_requires_live03_labels_and_abstains() -> None:
    with pytest.raises(
        ValueError, match="paper/counterfactual"
    ):
        LandingObservation(
            "paper",
            None,
            False,
            LabelState.POSITIVE,
            1,
            "route",
            "low",
        )
    rows = (
        LandingObservation(
            "a",
            "live03-a",
            True,
            LabelState.POSITIVE,
            10,
            "r",
            "low",
        ),
        LandingObservation(
            "b",
            "live03-b",
            True,
            LabelState.NEGATIVE,
            12,
            "r",
            "low",
        ),
        LandingObservation(
            "c",
            "live03-c",
            True,
            LabelState.POSITIVE,
            11,
            "r",
            "low",
        ),
    )
    prediction = LandingCostModel(rows).predict(
        route_class="r", fee_band="low"
    )
    assert prediction.blocked_reason is None
    assert prediction.probability == pytest.approx(2 / 3)
    blocked = LandingCostModel(()).predict(
        route_class="r", fee_band="low"
    )
    assert (
        blocked.blocked_reason
        == "INSUFFICIENT_LIVE03_LABELS"
    )


def test_factor_and_leadlag_research_remain_noncausal() -> None:
    factor = factor_cointegration_research(
        experiment_id="f",
        left=(1, 2, 3, 5, 8),
        right=(2, 3, 4, 7, 11),
        compute_cost_units=1,
    )
    lag = lead_lag_research(
        experiment_id="l",
        trigger=(0, 1, 0, 1, 0, 1),
        target=(0, 0, 1, 0, 1, 0),
        max_lag=1,
    )
    assert not factor.causal_claim
    assert not lag.causal_claim


def test_advanced_models_need_license_and_no_trading_authority() -> None:
    with pytest.raises(ValueError, match="licence"):
        AdvancedModelExperiment(
            "gnn",
            "upstream@sha",
            False,
            "rank",
            0.5,
            0.6,
            "holdout",
            10,
        )
    with pytest.raises(
        ValueError, match="trading authority"
    ):
        AdvancedModelExperiment(
            "gnn",
            "upstream@sha",
            True,
            "rank",
            0.5,
            0.6,
            "holdout",
            10,
            True,
        )


def test_protocol_invariant_monitor_keeps_unknown_distinct() -> None:
    check = InvariantCheck(
        "repayment_ratio", minimum=1.0
    )
    assert check.evaluate(None) == "unknown"
    assert check.evaluate(0.99) == "violation"
    assert check.evaluate(1.0) == "ok"


def test_regime_memory_requires_current_feature_schema() -> None:
    memory = RegimeMemory()
    memory.archive(
        RegimeModelSnapshot(
            "m1", "schema-a", "calm", "ctx", 0.7
        )
    )
    memory.archive(
        RegimeModelSnapshot(
            "m2", "schema-b", "calm", "ctx2", 0.8
        )
    )
    compatible = memory.compatible(
        feature_schema_hash="schema-a",
        regime_id="calm",
    )
    assert [item.model_id for item in compatible] == ["m1"]


def test_drift_requires_support_and_demotes_on_shift() -> None:
    small = drift_monitor(
        [1.0] * 5, [2.0] * 5
    )
    assert small.psi is None and not small.demote
    drifted = drift_monitor(
        [0.0] * 20, [10.0] * 20
    )
    assert drifted.demote and drifted.retrain


def test_model_registry_is_content_addressed() -> None:
    bundle = ModelBundle(
        "ranker",
        "artifact",
        "dataset",
        "code",
        "features",
        "split",
        "policy",
        ("calm",),
        ("shadow-only",),
        10,
    )
    registry = ModelRegistry()
    identity = registry.register(bundle)
    assert registry.get(identity) == bundle
    assert identity == bundle.identity


def test_champion_rejects_tail_or_cost_regression() -> None:
    champion = PromotionMetrics(
        0.7, 0.05, 10, 5
    )
    better = PromotionMetrics(
        0.8, 0.04, 9, 5
    )
    worse_tail = PromotionMetrics(
        0.9, 0.04, 20, 5
    )
    assert compare_champion_challenger(
        champion_identity="champ",
        challenger_identity="new",
        champion=champion,
        challenger=better,
        same_frozen_holdout=True,
    ).promoted
    assert not compare_champion_challenger(
        champion_identity="champ",
        challenger_identity="new",
        champion=champion,
        challenger=worse_tail,
        same_frozen_holdout=True,
    ).promoted


def test_value_of_information_keeps_mandatory_safety() -> None:
    policy = ValueOfInformationPolicy()
    with pytest.raises(
        ValueError, match="mandatory safety"
    ):
        policy.choose(
            (
                QueryCandidate(
                    "guard", 0.0, 5, True
                ),
                QueryCandidate(
                    "quote", 1.0, 1
                ),
            ),
            remaining_budget=2,
        )
    chosen = policy.choose(
        (
            QueryCandidate(
                "guard", 0.0, 1, True
            ),
            QueryCandidate("a", 2.0, 2),
            QueryCandidate("b", 1.0, 1),
        ),
        remaining_budget=4,
    )
    assert chosen is not None
    assert chosen.query_id == "a"


def test_world_model_and_stress_are_synthetic() -> None:
    world = MarketWorldModel(
        "state", "flows", ("private_orderflow",)
    )
    scenario = ExogenousScenario(
        "shock", 1.0, 2.0, 3.0
    )
    result = world.scenario(scenario)
    assert result["synthetic"] is True
    stress = run_stress_scenarios(
        baseline_net=60, scenarios=(scenario,)
    )
    assert stress[0].conservative_net == 10
    assert (
        stress[0].observed_market_evidence is False
    )


def test_capacity_forbids_linear_profit_extrapolation() -> None:
    report = CapacityReflexivityReport(
        (1, 2, 4), (10, 15, 12), 0.25
    )
    assert not report.linear_extrapolation_allowed
    with pytest.raises(
        ValueError, match="linear extrapolation"
    ):
        CapacityReflexivityReport(
            (1,), (10,), 0.0, True
        )


def test_symbolic_factory_requires_verified_closed_debt_units() -> None:
    factory = SymbolicStrategyFactory(
        (
            StrategyPrimitive(
                "borrow", "SOL", "SOL", debt_delta=1
            ),
            StrategyPrimitive(
                "swap", "SOL", "USDC"
            ),
            StrategyPrimitive(
                "swap_back", "USDC", "SOL"
            ),
            StrategyPrimitive(
                "repay", "SOL", "SOL", debt_delta=-1
            ),
        )
    )
    spec = factory.compose(
        ("borrow", "swap", "swap_back", "repay")
    )
    assert spec.debt_closed and spec.research_only
    with pytest.raises(ValueError, match="open debt"):
        factory.compose(
            ("borrow", "swap", "swap_back")
        )
    with pytest.raises(
        ValueError, match="unverified primitive"
    ):
        factory.compose(("invented",))


def test_offline_policy_rejects_out_of_support_reward() -> None:
    baseline = OfflinePolicyCandidate(
        "baseline", 1.0, 1.0, 0.1
    )
    unsupported = OfflinePolicyCandidate(
        "rl", 0.2, 100.0, 0.1
    )
    decision = evaluate_offline_policies(
        baseline, (unsupported,)
    )
    assert decision.selected_policy_id == "baseline"
    assert not decision.live_exploration_allowed


def test_learning_acceptance_is_scoped_and_no_live_authority() -> None:
    verdict = qualify_learning_layer(
        (
            LearningTaskEvidence(
                "rank",
                True,
                0.1,
                3,
                True,
                True,
                True,
            ),
            LearningTaskEvidence(
                "landing",
                True,
                None,
                0,
                True,
                False,
                True,
            ),
        )
    )
    assert verdict.accepted_tasks == ("rank",)
    assert verdict.blocked_tasks == ("landing",)
    assert verdict.operational_status == "IMPLEMENTED_OFFLINE"
    assert verdict.live_authority_granted is False
