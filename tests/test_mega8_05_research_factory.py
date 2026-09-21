"""MEGA8-05 focused regressions for PR-239..254 / NF-641..704."""

from __future__ import annotations

import inspect

import pytest

from src.research.mega8_05 import (
    Disposition,
    apply_multiple_test_correction,
    archive_regime_transition,
    audit_selection_bias,
    bind_dataset_cutoff,
    build_golden_vector_pack,
    build_information_flow_graph,
    classify_copy_eligibility,
    classify_wallet_flow,
    collect_promotion_evidence,
    detect_factor_residual,
    detect_liquidity_withdrawal_risk,
    detect_structural_break,
    define_adapter_conformance_contract,
    discover_cointegrated_baskets,
    discover_unknown_deployment,
    discover_upstream_release_candidates,
    enforce_dynamic_asset_quarantine,
    enforce_source_reuse_policy,
    enumerate_hypothesis_family,
    estimate_factor_exposures,
    estimate_false_discovery_rate,
    estimate_flow_toxicity,
    estimate_hedge_vector,
    estimate_multiscale_lead_lag,
    extract_candidate_symbols,
    fit_dynamic_factor_model,
    freeze_analysis_plan,
    gate_discovery_claim,
    generate_abi_read_adapter,
    generate_attribution_bundle,
    generate_idl_account_decoder,
    generate_move_resource_decoder,
    infer_account_relationships,
    infer_market_regime,
    infer_meta_order,
    infer_shared_resource_dependencies,
    label_missingness_mechanism,
    link_wallet_program_relationships,
    model_mean_reversion_half_life,
    model_observation_selection,
    monitor_authority_mutations,
    promote_discovered_capability,
    promote_predictive_link,
    publish_adapter_qualification,
    publish_entity_graph,
    publish_preregistered_experiment,
    publish_upstream_research_dossier,
    qualify_stat_arb_basket,
    quarantine_unknown_market,
    rank_reuse_opportunity,
    reconstruct_cpi_call_graph,
    register_research_hypothesis,
    resolve_asset_entities,
    resolve_protocol_entities,
    route_flow_signal,
    route_policy_by_regime,
    run_adapter_differential_suite,
    scan_license_surface,
    score_honeypot_or_rug_behavior,
    test_lead_lag_stability as evaluate_lead_lag_stability,
    update_online_covariance,
    validate_generated_adapter,
    validate_inferred_semantics,
    weight_selective_samples,
)
from src.research.mega8_05.base import ResearchArtifact


def _assert_offline(artifact: ResearchArtifact) -> None:
    assert artifact.signer_allowed is False
    assert artifact.submission_allowed is False
    assert artifact.live_allowed is False


def test_pr239_upstream_discovery_is_deduplicated_and_never_imports() -> None:
    releases = [
        {
            "repository": "official/protocol",
            "immutable_ref": "a" * 40,
            "release": "v1",
            "license_id": "MIT",
            "official": True,
        },
        {
            "repository": "official/protocol",
            "immutable_ref": "a" * 40,
            "release": "v1",
            "license_id": "MIT",
            "official": True,
        },
        {
            "repository": "fork/protocol",
            "immutable_ref": "b" * 40,
            "official": False,
        },
    ]
    candidates = discover_upstream_release_candidates(releases)
    assert len(candidates) == 1
    enriched = {
        **candidates[0],
        "official": True,
        "paths": ["src/lib.py"],
        "symbols": ["quote"],
        "callers": ["router"],
        "tests": ["test_quote"],
        "usefulness": 4,
        "maturity": 4,
        "test_quality": 3,
        "integration_cost": 2,
    }
    assert extract_candidate_symbols(enriched)["symbols"] == ("quote",)
    assert rank_reuse_opportunity([enriched])[0]["reuse_score"] == 9
    dossier = publish_upstream_research_dossier(enriched)
    assert dossier.disposition is Disposition.PASS
    assert dossier.payload["auto_import_allowed"] is False
    assert dossier.payload["code_execution_allowed"] is False
    _assert_offline(dossier)


def test_pr240_codegen_is_deterministic_and_signer_free() -> None:
    digest = "1" * 64
    idl = generate_idl_account_decoder(digest, ["reserve", "owner"])
    abi = generate_abi_read_adapter(digest, ["balanceOf"])
    move = generate_move_resource_decoder(digest, ["Pool"])
    assert idl == generate_idl_account_decoder(digest, ["owner", "reserve"])
    for source in (idl, abi, move):
        assert "SIGNING_ALLOWED = False" in source
        assert "SUBMISSION_ALLOWED = False" in source
    verdict = validate_generated_adapter(
        idl,
        schema_sha256=digest,
        golden_vectors=[{"matched": True}, {"matched": True}],
    )
    assert verdict.disposition is Disposition.PASS
    assert verdict.payload["generated_code_executed"] is False


def test_pr241_adapter_contract_separates_quote_and_execution_authority() -> None:
    contract = define_adapter_conformance_contract(
        adapter_id="demo",
        deployment_id="chain:deployment",
        schema_sha256="2" * 64,
        quote_supported=True,
        build_supported=False,
    )
    vectors = build_golden_vector_pack(
        [
            {"vector_id": "ok", "input": 1, "expected": 2},
            {
                "vector_id": "malicious",
                "input": -1,
                "expected": "reject",
                "malicious": True,
            },
        ]
    )
    differential = run_adapter_differential_suite({"a": 1}, {"a": 1})
    qualification = publish_adapter_qualification(
        contract, vectors, differential, version="v1"
    )
    assert qualification.disposition is Disposition.PASS
    assert qualification.payload["execution_authority"] is False


def test_pr242_unknown_market_stays_quarantined_until_existing_authority() -> None:
    deployment = discover_unknown_deployment(
        {
            "chain": "solana",
            "deployment_id": "program-1",
            "binary_identity": "bin",
            "schema_identity": "schema",
            "known": False,
        }
    )
    quarantine = quarantine_unknown_market(deployment, "pool-1")
    assert quarantine.disposition is Disposition.BLOCKED
    evidence = collect_promotion_evidence(
        binary_verified=True,
        schema_verified=True,
        owner_verified=True,
        upgrade_authority_verified=True,
        liquidity_verified=True,
        liquid_exit_verified=True,
    )
    blocked = promote_discovered_capability(
        quarantine, evidence, authority_receipt=None
    )
    assert blocked.disposition is Disposition.BLOCKED
    ready = promote_discovered_capability(
        quarantine, evidence, authority_receipt="release-authority:receipt"
    )
    assert ready.disposition is Disposition.PASS
    assert ready.payload["promotion_applied_by_this_module"] is False


def test_pr243_inferred_semantics_are_hypotheses_until_validated() -> None:
    graph = reconstruct_cpi_call_graph(
        [{"parent": "a", "child": "b", "depth": 1}]
    )
    accounts = infer_account_relationships(
        [{"account": "vault", "candidate_role": "reserve"}]
    )
    shared = infer_shared_resource_dependencies(
        [
            {"operation": "x", "resources": ["pool"]},
            {"operation": "y", "resources": ["pool"]},
        ]
    )
    assert accounts.payload["executable"] is False
    assert shared.payload["validated"] is False
    verdict = validate_inferred_semantics(
        graph, fixture_match=True, invariant_match=True
    )
    assert verdict.disposition is Disposition.PASS
    assert verdict.payload["execution_promotion"] is False


def test_pr244_license_policy_fails_closed_on_unknown_or_incomplete_copy() -> None:
    surface = scan_license_surface(
        [{"path": "src/x.py", "license_id": "UNKNOWN", "source_sha256": "x"}]
    )
    assert surface.disposition is Disposition.BLOCKED
    unknown = classify_copy_eligibility(["UNKNOWN"], requested_mode="PORT")
    assert unknown.disposition is Disposition.BLOCKED
    assert unknown.payload["decision"] == "REFERENCE_ONLY"
    eligible = classify_copy_eligibility(["MIT"], requested_mode="PORT")
    attribution = generate_attribution_bundle(
        source_repository="official/repo",
        immutable_ref="abc",
        source_hashes=["sha"],
        notices=["MIT"],
    )
    assert (
        enforce_source_reuse_policy(eligible, None).disposition
        is Disposition.BLOCKED
    )
    assert (
        enforce_source_reuse_policy(eligible, attribution).disposition
        is Disposition.PASS
    )


def test_pr245_preregistration_identity_changes_when_plan_changes() -> None:
    hypothesis = register_research_hypothesis(
        hypothesis_id="h1",
        mechanism_claim="lag predicts residual",
        falsification_rule="holdout gain <= 0",
    )
    plan = freeze_analysis_plan(
        metrics=["net"],
        statistical_tests=["bootstrap"],
        stopping_rules=["n=100"],
        selection_rules=["all"],
    )
    cutoff = bind_dataset_cutoff(
        train_end="2026-01-01",
        validation_end="2026-02-01",
        holdout_end="2026-03-01",
    )
    experiment = publish_preregistered_experiment(hypothesis, plan, cutoff)
    changed = freeze_analysis_plan(
        metrics=["net", "latency"],
        statistical_tests=["bootstrap"],
        stopping_rules=["n=100"],
        selection_rules=["all"],
    )
    revised = publish_preregistered_experiment(hypothesis, changed, cutoff)
    assert experiment.identity != revised.identity


def test_pr246_multiple_testing_requires_corrected_economic_evidence() -> None:
    family = enumerate_hypothesis_family(["h1", "h2", "h3"])
    assert family.payload["denominator"] == 3
    correction = apply_multiple_test_correction(
        {"h1": 0.001, "h2": 0.3, "h3": 0.6}
    )
    summary = estimate_false_discovery_rate(correction, alpha=0.05)
    assert "h1" in summary.payload["discoveries"]
    passed = gate_discovery_claim(
        correction,
        "h1",
        alpha=0.05,
        economic_effect_positive=True,
        executable_evidence_present=True,
    )
    blocked = gate_discovery_claim(
        correction,
        "h1",
        alpha=0.05,
        economic_effect_positive=True,
        executable_evidence_present=False,
    )
    assert passed.disposition is Disposition.PASS
    assert blocked.disposition is Disposition.BLOCKED


def test_pr247_selection_labels_do_not_fabricate_landing_outcomes() -> None:
    model = model_observation_selection(
        [{"selected": True}, {"selected": False}, {"selected": False}]
    )
    assert model.payload["selection_rate"] == pytest.approx(1 / 3)
    label = label_missingness_mechanism("quota-exhausted")
    assert label.payload["mechanism"] == "resource-censoring"
    weights = weight_selective_samples([0.5, 0.01], max_weight=10)
    assert weights.payload["weights"] == (2.0, 10.0)
    audit = audit_selection_bias(
        ["observed", "quota-exhausted", "provider-gap"], weights
    )
    assert audit.payload["landing_label_for_unsent_allowed"] is False


def test_pr248_entity_resolution_never_merges_by_ticker_alone() -> None:
    assets = resolve_asset_entities(
        [
            {"chain": "solana", "address": "mint-a", "aliases": ["USDC"]},
            {"chain": "ethereum", "address": "0xabc", "aliases": ["USDC"]},
        ]
    )
    assert len(assets.payload["entities"]) == 2
    assert assets.payload["ticker_only_merge_allowed"] is False
    protocols = resolve_protocol_entities(
        [
            {
                "chain": "solana",
                "deployment_id": "prog",
                "venue": "dex",
                "valid_from": "1",
            }
        ]
    )
    links = link_wallet_program_relationships(
        [
            {
                "wallet": "wallet",
                "program": "prog",
                "relationship": "observed-call",
                "confidence": 0.7,
            }
        ]
    )
    graph = publish_entity_graph(assets, protocols, links)
    assert graph.disposition is Disposition.PASS
    assert links.payload["deanonymization_claimed"] is False


def test_pr249_factor_residual_is_research_only() -> None:
    series = {
        "a": [1.0, 2.0, 3.0, 4.0],
        "b": [2.0, 3.0, 4.0, 5.0],
    }
    covariance_artifact = update_online_covariance(series)
    assert covariance_artifact.payload["leakage_safe"] is True
    model = fit_dynamic_factor_model(series)
    exposures = estimate_factor_exposures(series, model)
    residual = detect_factor_residual(
        {"a": 5.0, "b": 6.0}, exposures, factor_value=5.5
    )
    assert residual.payload["execution_signal"] is False


def test_pr250_stat_arb_is_non_atomic_and_requires_separate_margin() -> None:
    candidates = discover_cointegrated_baskets(
        {"a/b": ([1, 2, 3, 4], [1, 2, 3, 4])}
    )
    assert candidates.payload["research_only"] is True
    hedge = estimate_hedge_vector([1, 2, 3], [2, 4, 6])
    assert "beta" in hedge.payload
    half_life = model_mean_reversion_half_life([1.0, 0.5, 0.25, 0.1])
    assert half_life.payload["statistical_not_observed_edge_duration"] is True
    blocked = qualify_stat_arb_basket(
        preregistered=True,
        multiple_testing_corrected=True,
        temporal_holdout_positive=True,
        all_costs_included=True,
        inventory_margin_qualified=False,
    )
    assert blocked.disposition is Disposition.BLOCKED
    assert blocked.payload["inherits_atomic_permission"] is False


def test_pr251_unknown_regime_fails_to_no_trade() -> None:
    short = infer_market_regime([0.1, 0.2])
    routed = route_policy_by_regime(short, {"quiet": "policy-a"})
    assert routed.disposition is Disposition.BLOCKED
    assert routed.payload["policy"] == "no-trade"
    break_artifact = detect_structural_break([1, 1, 1, 3, 3, 3])
    assert "detected" in break_artifact.payload
    current = infer_market_regime([0.0, 0.0, 0.0, 0.0])
    transition = archive_regime_transition(short, current)
    assert transition.payload["history_rewritten"] is False


def test_pr252_lead_lag_promotes_feature_not_execution_authority() -> None:
    train = estimate_multiscale_lead_lag(
        [1, 2, 3, 4, 5, 6], [0, 1, 2, 3, 4, 5], max_lag=2
    )
    holdout = estimate_multiscale_lead_lag(
        [2, 3, 4, 5, 6, 7], [1, 2, 3, 4, 5, 6], max_lag=2
    )
    graph = build_information_flow_graph({"a->b": train})
    assert graph.payload["time_versioned"] is True
    stable = evaluate_lead_lag_stability(train, holdout, tolerance=0.01)
    promoted = promote_predictive_link(
        stable,
        stale_data_alternative_rejected=True,
        common_cause_alternative_tested=True,
    )
    assert promoted.disposition is Disposition.PASS
    assert promoted.payload["execution_authority"] is False


def test_pr253_flow_is_public_research_only_and_no_harmful_frontrun() -> None:
    classified = classify_wallet_flow(
        [{"wallet": "w", "signed_amount": 10.0}]
    )
    assert classified.payload["deanonymization_claimed"] is False
    meta = infer_meta_order([1, 2, 3, 4])
    assert meta.disposition is Disposition.PASS
    toxicity = estimate_flow_toxicity([1, -1], [-1, 1])
    assert toxicity.payload["toxicity"] == 1.0
    routed = route_flow_signal(meta, destination="ranking", minimum_confidence=0.1)
    assert routed.payload["harmful_frontrunning_allowed"] is False
    with pytest.raises(ValueError):
        route_flow_signal(meta, destination="submission")


def test_pr254_data_gap_is_not_mislabeled_rug_and_quarantine_is_fail_closed() -> None:
    authority = monitor_authority_mutations(
        {"mint_authority": "a"}, {"mint_authority": "b"}
    )
    liquidity = detect_liquidity_withdrawal_risk(
        previous_executable_liquidity=None,
        current_executable_liquidity=100,
    )
    behavior = score_honeypot_or_rug_behavior(
        buy_success_rate=None,
        exit_success_rate=None,
        authority_mutation=False,
    )
    assert liquidity.disposition is Disposition.UNKNOWN
    assert behavior.payload["rug_label"] is False
    quarantine = enforce_dynamic_asset_quarantine(
        authority,
        liquidity,
        behavior,
        unknown_extension=False,
    )
    assert quarantine.disposition is Disposition.BLOCKED
    assert quarantine.payload["admitted"] is False


def test_exact_public_function_count_and_no_effectful_surface() -> None:
    import src.research.mega8_05 as mega

    functions = [
        value
        for name, value in vars(mega).items()
        if inspect.isfunction(value) and not name.startswith("_")
    ]
    assert len(functions) == 64
    forbidden = ("sign", "submit", "send_transaction", "transfer_funds")
    names = {function.__name__ for function in functions}
    assert not any(name in names for name in forbidden)
