from __future__ import annotations

import pytest

from src.research import (
    AccelerationBenchmark,
    AgentExperimentPlan,
    AgentRoleDecision,
    ApplicationOrDisclosureReceipt,
    BenchmarkClass,
    BenchmarkMeasurement,
    CashState,
    DataEvidenceApi,
    DataEvidenceArtifact,
    DataEvidenceKind,
    DefensiveToolBenchmark,
    DevelopmentWorkflowReceipt,
    EvidenceStatus,
    FederatedExperiment,
    HypothesisRecord,
    KeeperAuthorization,
    PaymasterCapability,
    PromotionDecisionKind,
    QuboBenchmark,
    QuantumModelExperiment,
    ResearchClaim,
    ResearchDisposition,
    ResearchEvidenceLibrary,
    ResearchExperimentManifest,
    ResearchFailure,
    ResearchOutcome,
    ResearchSource,
    RevenueAttributionLedger,
    RevenueCashflow,
    RevenueCategory,
    SourceKind,
    SponsorBudget,
    VerifiabilityPrototype,
    build_cited_research_result,
    compare_measurements,
    evaluate_research_promotion,
    plan_keeper_operation,
    plan_sponsored_execution,
)

A, B, C, D, E, F = (char * 64 for char in "abcdef")


def source(source_id: str = "official", *, digest: str = A, kind: SourceKind = SourceKind.OFFICIAL, group: str = "maintainer") -> ResearchSource:
    return ResearchSource(source_id, kind, "v1", digest, "MIT" if kind is SourceKind.CODE else None, f"https://example.invalid/{source_id}", EvidenceStatus.VERIFIED, group)


def measurement(name: str, backend: BenchmarkClass, *, extra_us: int = 0, result: str = C, budget: int = 100) -> BenchmarkMeasurement:
    return BenchmarkMeasurement(name, backend, A, B, result, True, 100 + extra_us, 100, 100, 1000, 100, 10, 1024, budget)


def test_nf308_evidence_library_identity_independence_and_conflict() -> None:
    lib = ResearchEvidenceLibrary()
    lib.add_source(source())
    lib.add_source(source("paper", digest=B, kind=SourceKind.PAPER, group="paper-authors"))
    lib.add_claim(ResearchClaim("claim", "measured", ("official", "paper"), EvidenceStatus.VERIFIED))
    lib.add_hypothesis(HypothesisRecord("hyp", "does it help?", ("NF-308",), ("official",), ResearchDisposition.RESEARCH))
    assert lib.independent_verified_groups("claim") == ("maintainer", "paper-authors")
    assert len(lib.snapshot()["sha256"]) == 64
    with pytest.raises(ResearchFailure, match="SOURCE_ID_CONFLICT"):
        lib.add_source(source(digest=C))


def test_nf309_copilot_has_exact_citations_and_no_authority() -> None:
    lib = ResearchEvidenceLibrary(); lib.add_source(source())
    result = build_cited_research_result(library=lib, question="map", cited_source_ids=("official",), suggested_symbols=("known", "invented"), known_symbols=("known",))
    assert result.missing_symbols == ("invented",)
    assert not result.live_approval_allowed and not result.signing_allowed
    with pytest.raises(ResearchFailure, match="SOURCE_MISSING"):
        build_cited_research_result(library=lib, question="bad", cited_source_ids=("missing",))
    manifest = ResearchExperimentManifest("exp", "hyp", "cpu", A, B, C, ("official",), 10)
    assert len(manifest.manifest_sha256) == 64
    with pytest.raises(ValueError, match="hidden evaluation"):
        ResearchExperimentManifest("hidden", "hyp", "cpu", A, B, C, ("official",), 10, hidden_data_allowed=True)


def test_nf310_developer_workflow_never_collects_credentials() -> None:
    receipt = DevelopmentWorkflowReceipt("task", "BobIvans/studious-pancake", A, "branch", ("src/research/evidence.py",), ("pytest",), B, True)
    assert not receipt.password_collection_allowed and not receipt.private_key_access_allowed
    with pytest.raises(ValueError, match="passwords/private keys"):
        DevelopmentWorkflowReceipt("bad", "repo", A, "branch", ("x",), ("pytest",), B, False, private_key_access_allowed=True)


def test_nf311_agents_share_budget_but_agreement_is_not_market_proof() -> None:
    plan = AgentExperimentPlan(
        "agents", 10,
        AgentRoleDecision("planner", "try", ("e1",)),
        AgentRoleDecision("critic", "reject", ("e2",)),
        AgentRoleDecision("runner", "blocked", ("e3",)),
        A,
    )
    assert plan.disagreement and plan.market_proof_count == 0 and not plan.live_vote_allowed


def test_nf312_defensive_tool_is_measurement_not_execution() -> None:
    bench = DefensiveToolBenchmark("tool", "source", A, "local-fixtures", True, False, 7, 3, 2)
    assert not bench.qualified and bench.measured_false_positive_rate == pytest.approx(0.3)
    assert not bench.execution_permission


def test_nf313_qubo_requires_equal_budget_classical_baseline_and_exact_recheck() -> None:
    base, qpu = measurement("cpu", BenchmarkClass.CLASSICAL, extra_us=500), measurement("qpu", BenchmarkClass.QUANTUM_SIMULATOR)
    comparison = compare_measurements(experiment_id="qubo", baseline=base, challenger=qpu)
    record = QuboBenchmark(comparison, D, E, True, True)
    assert record.benchmark.outcome is ResearchOutcome.POSITIVE and not record.quantum_advantage_claimed
    mismatched = measurement("qpu2", BenchmarkClass.QUANTUM_HARDWARE, budget=101)
    assert compare_measurements(experiment_id="blocked", baseline=base, challenger=mismatched).outcome is ResearchOutcome.BLOCKED


def test_nf314_quantum_model_cannot_import_paper_metric() -> None:
    with pytest.raises(ValueError, match="paper accuracy"):
        QuantumModelExperiment("qmodel", measurement("c", BenchmarkClass.CLASSICAL), measurement("q", BenchmarkClass.QUANTUM_INSPIRED), F, "f1", 500000, 510000, False, True)


def test_nf315_acceleration_measures_whole_pipeline_and_exact_vectors() -> None:
    comp = compare_measurements(experiment_id="gpu", baseline=measurement("cpu", BenchmarkClass.CPU, extra_us=500), challenger=measurement("gpu", BenchmarkClass.GPU))
    assert AccelerationBenchmark(comp, D, E).benchmark.latency_delta_us < 0
    wrong = compare_measurements(experiment_id="wrong", baseline=measurement("cpu2", BenchmarkClass.CPU), challenger=measurement("gpu2", BenchmarkClass.GPU, result=D))
    with pytest.raises(ValueError, match="exact result"):
        AccelerationBenchmark(wrong, D, E)


def test_nf316_federated_learning_requires_privacy_consent_and_poisoning_bound() -> None:
    ok = FederatedExperiment("fl", A, B, C, D, 3, 1024, 500000, 490000, True)
    assert ok.communication_bytes == 1024
    with pytest.raises(ResearchFailure, match="POISONING_BOUND_MISSING"):
        FederatedExperiment("flbad", A, B, C, D, 3, 1024, 500000, 490000, False)
    with pytest.raises(ResearchFailure, match="RAW_DATA_EXFILTRATION"):
        FederatedExperiment("flleak", A, B, C, D, 3, 1024, 500000, 490000, True, True)


def test_nf317_verifiable_computation_does_not_prove_market_truth() -> None:
    proto = VerifiabilityPrototype("zk", A, B, C, D, E, 1000, 10, 128, 5)
    assert proto.proof_bytes == 128
    with pytest.raises(ValueError, match="market input truth"):
        VerifiabilityPrototype("badzk", A, B, C, D, E, 1000, 10, 128, 5, True)


def paymaster_capability(*, verified: bool, funded: bool) -> PaymasterCapability:
    return PaymasterCapability("kora", A, funded, ("USDC",), 100, B, verified)


def sponsor_budget() -> SponsorBudget:
    return SponsorBudget("sponsor", "SOL", 1000, 10, 100, 50)


def test_nf318_paymaster_requires_external_proof_funding_caps_and_never_signs() -> None:
    blocked = plan_sponsored_execution(plan_id="p1", capability=paymaster_capability(verified=False, funded=False), budget=sponsor_budget(), transaction_sha256=C, customer_id="customer", payment_asset_id="USDC", sponsor_fee_base_units=20, client_service_fee_base_units=3, roles_validated=True)
    assert not blocked.approved and {"PAYMASTER_CAPABILITY_UNVERIFIED", "PAYMASTER_FEE_PAYER_UNFUNDED"}.issubset(blocked.blockers)
    ok = plan_sponsored_execution(plan_id="p2", capability=paymaster_capability(verified=True, funded=True), budget=sponsor_budget(), transaction_sha256=C, customer_id="customer", payment_asset_id="USDC", sponsor_fee_base_units=20, client_service_fee_base_units=3, roles_validated=True)
    assert ok.approved and not ok.signing_allowed and not ok.submission_allowed


def test_nf319_keeper_authorization_caps_debit_and_excludes_client_capital() -> None:
    auth = KeeperAuthorization("auth", "customer", "position-1", ("rebalance",), 100, 2, A, True)
    blocked = plan_keeper_operation(operation_id="op", authorization=auth, action="withdraw", desired_state_sha256=B, observed_state_sha256=C, worst_debit_base_units=101)
    assert not blocked.permitted and "KEEPER_ACTION_OUT_OF_SCOPE" in blocked.blockers and "KEEPER_MAX_DEBIT_EXCEEDED" in blocked.blockers
    assert not blocked.client_capital_is_trading_capital


def test_nf320_data_api_tracks_kind_rights_staleness_scope_and_budget() -> None:
    artifact = DataEvidenceArtifact("report", "v1", A, B, DataEvidenceKind.SIMULATED, True, ("research",), 1, stale=True)
    api = DataEvidenceApi((artifact,))
    result = api.read(artifact_id="report", lease_id="lease", access_scope="research")
    assert result.stale and not result.actual_pnl_claimed and result.remaining_queries == 0
    with pytest.raises(ResearchFailure, match="QUERY_BUDGET_EXHAUSTED"):
        api.read(artifact_id="report", lease_id="lease", access_scope="research")
    restricted = DataEvidenceApi((DataEvidenceArtifact("private", "v1", C, D, DataEvidenceKind.OBSERVED, False, ("research",), 1),))
    with pytest.raises(ResearchFailure, match="DISTRIBUTION_DENIED"):
        restricted.read(artifact_id="private", lease_id="lease", access_scope="research")


def test_nf321_grant_bounty_receipt_is_not_submission_exploit_or_revenue() -> None:
    receipt = ApplicationOrDisclosureReceipt("grant", "program", A, B, True, True, False, False)
    assert not receipt.submitted and not receipt.exploitation_performed and not receipt.revenue_recognized
    with pytest.raises(ResearchFailure, match="IDENTITY_APPROVAL_MISSING"):
        ApplicationOrDisclosureReceipt("bad", "program", A, B, False, True, False, False)


def test_nf322_product_accounting_separates_signed_pnl_product_rent_client_and_pending() -> None:
    ledger = RevenueAttributionLedger()
    rows = (
        RevenueCashflow("trade-win", "ev-win", RevenueCategory.ARBITRAGE_PNL, "USDC", 10, "market", CashState.SETTLED, A),
        RevenueCashflow("trade-loss", "ev-loss", RevenueCategory.ARBITRAGE_PNL, "USDC", -12, "market", CashState.SETTLED, F),
        RevenueCashflow("service", "ev-service", RevenueCategory.SERVICE_FEE, "USDC", 5, "customer", CashState.SETTLED, B),
        RevenueCashflow("rent", "ev-rent", RevenueCategory.RENT_RECLAIM, "USDC", 3, "self", CashState.SETTLED, C),
        RevenueCashflow("client", "ev-client", RevenueCategory.CLIENT_FUNDS, "USDC", 100, "customer", CashState.SETTLED, D),
        RevenueCashflow("grant", "ev-grant", RevenueCategory.GRANT, "USDC", 50, "grantor", CashState.PENDING, E),
    )
    for row in rows: ledger.record(row)
    assert (ledger.trading_pnl("USDC"), ledger.product_revenue("USDC"), ledger.non_alpha_recovery("USDC"), ledger.client_funds("USDC")) == (-2, 5, 3, 100)
    assert ledger.export()["trading_capital_authority"] is False
    with pytest.raises(ResearchFailure, match="DOUBLE_ATTRIBUTION"):
        ledger.record(RevenueCashflow("dup", "ev-service", RevenueCategory.REBATE, "USDC", 1, "provider", CashState.SETTLED, F))


def promotion(outcome: ResearchOutcome, *, risk: bool = False):
    return evaluate_research_promotion(experiment_id=f"promo-{outcome.value}", benchmark_sha256=A, baseline_sha256=B, outcome=outcome, reproducible=True, end_to_end_cost_measured=True, safety_reviewed=True, integration_tests_passed=True, resource_policy_satisfied=True, requested_risk_increase=risk)


def test_nf323_promotion_preserves_negative_evidence_and_never_self_promotes_live() -> None:
    negative = promotion(ResearchOutcome.NEGATIVE)
    assert negative.decision is PromotionDecisionKind.REJECTED_WITH_EVIDENCE
    positive = promotion(ResearchOutcome.POSITIVE)
    assert positive.decision is PromotionDecisionKind.SCOPED_INTEGRATION_REVIEW
    assert not positive.execution_authority_granted and not positive.production_ready
    assert promotion(ResearchOutcome.POSITIVE, risk=True).decision is PromotionDecisionKind.BLOCKED


def test_integrated_agg14_benchmark_to_review_keeps_product_revenue_separate() -> None:
    base, gpu = measurement("cpu-i", BenchmarkClass.CPU, extra_us=500), measurement("gpu-i", BenchmarkClass.GPU)
    comp = compare_measurements(experiment_id="integrated", baseline=base, challenger=gpu)
    decision = evaluate_research_promotion(experiment_id="integrated", benchmark_sha256=comp.reproducible_sha256, baseline_sha256=base.identity_sha256, outcome=comp.outcome, reproducible=True, end_to_end_cost_measured=True, safety_reviewed=True, integration_tests_passed=True, resource_policy_satisfied=True, requested_risk_increase=False)
    assert decision.decision is PromotionDecisionKind.SCOPED_INTEGRATION_REVIEW and not decision.execution_authority_granted
    ledger = RevenueAttributionLedger()
    ledger.record(RevenueCashflow("trade", "trade-event", RevenueCategory.ARBITRAGE_PNL, "USDC", 7, "market", CashState.SETTLED, A))
    ledger.record(RevenueCashflow("service", "service-event", RevenueCategory.SERVICE_FEE, "USDC", 3, "customer", CashState.SETTLED, B))
    assert ledger.trading_pnl("USDC") == 7 and ledger.product_revenue("USDC") == 3
