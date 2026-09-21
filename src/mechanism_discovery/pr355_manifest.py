"""PR-355 NXF ownership manifest.

NXF identities remain provisional requirement IDs and intentionally do not
allocate NF-1185+.
"""

from __future__ import annotations

GROUPS = {
    "NX-00": {
        "module": "pr355_delta",
        "start": 1,
        "names": [
            "map_delta_to_current_owners",
            "classify_delta_non_duplication",
            "bind_delta_source_provenance",
            "register_delta_marketpack",
            "audit_delta_effect_boundary",
            "publish_delta_coverage_receipt"
        ]
    },
    "NX-01": {
        "module": "claims",
        "start": 7,
        "names": [
            "define_cashflow_stream",
            "define_claim_right",
            "normalize_rate_instrument",
            "compile_fixed_floating_payoff",
            "price_cashflow_after_costs",
            "qualify_cashflow_identity"
        ]
    },
    "NX-02": {
        "module": "liquidity_shape",
        "start": 13,
        "names": [
            "define_liquidity_shape",
            "compile_liquidity_shape_surface",
            "project_dynamic_liquidity_shape",
            "compare_hybrid_execution_paths",
            "estimate_lvr_and_lp_response",
            "stress_liquidity_shape"
        ]
    },
    "NX-03": {
        "module": "programmable_cash",
        "start": 19,
        "names": [
            "register_programmable_cash_asset",
            "model_earning_and_claim_modes",
            "read_mint_redeem_capacity",
            "detect_extension_parity_residual",
            "decompose_synthetic_dollar_backing",
            "qualify_redemption_eligibility"
        ]
    },
    "NX-04": {
        "module": "rwa",
        "start": 25,
        "names": [
            "register_rwa_instrument_rights",
            "ingest_nav_revision_history",
            "model_rwa_subscription_redemption",
            "model_custody_receipt_state",
            "detect_rwa_nav_basis",
            "qualify_rwa_access_path"
        ]
    },
    "NX-05": {
        "module": "shared_credit",
        "start": 31,
        "names": [
            "map_hub_spoke_liquidity",
            "normalize_spoke_risk_parameters",
            "compute_shared_liquidity_bottleneck",
            "simulate_cross_spoke_utilization",
            "detect_hub_spoke_basis",
            "qualify_shared_credit_route"
        ]
    },
    "NX-06": {
        "module": "mechanism_transfer",
        "start": 37,
        "names": [
            "build_mechanism_fingerprint",
            "build_marketpack_adapter_features",
            "train_local_only_baseline",
            "train_mechanism_transfer_challenger",
            "measure_negative_transfer",
            "promote_or_reject_transfer"
        ]
    },
    "NX-07": {
        "module": "frontier",
        "start": 43,
        "names": [
            "estimate_marketpack_information_value",
            "estimate_marketpack_onboarding_cost",
            "score_research_frontier",
            "allocate_capture_budget_by_frontier",
            "audit_frontier_selection_bias",
            "retire_low_value_marketpack"
        ]
    },
    "NX-08": {
        "module": "research_receipt",
        "start": 49,
        "names": [
            "build_research_receipt_manifest",
            "replay_receipt_computation",
            "generate_optional_computation_proof",
            "verify_computation_proof",
            "redact_receipt_for_sharing",
            "bind_receipt_to_evidence_ledger"
        ]
    },
    "NX-09": {
        "module": "research_resources",
        "start": 55,
        "names": [
            "register_paid_research_resource",
            "discover_paid_resource",
            "quote_research_purchase",
            "authorize_bounded_resource_purchase",
            "reconcile_resource_payment",
            "score_information_value_after_payment"
        ]
    },
    "NX-10": {
        "module": "incident_admission",
        "start": 61,
        "names": [
            "ingest_protocol_incident",
            "derive_incident_invariant_tests",
            "build_adversarial_mechanism_states",
            "quarantine_vulnerable_deployment",
            "detect_semantic_security_drift",
            "gate_mechanism_admission_on_security"
        ]
    },
    "NX-11": {
        "module": "causal_twin",
        "start": 67,
        "names": [
            "define_market_intervention",
            "declare_causal_assumptions",
            "simulate_intervention_twin",
            "compare_observed_and_counterfactual",
            "estimate_intervention_uncertainty",
            "reject_unsupported_causal_claim"
        ]
    }
}

NXF_TO_SYMBOL = {
    f"NXF-{spec['start'] + offset:03d}": (group, spec["module"], symbol)
    for group, spec in GROUPS.items()
    for offset, symbol in enumerate(spec["names"])
}
NXF_IDS = tuple(NXF_TO_SYMBOL)
ALL_FUNCTIONS = tuple(NXF_TO_SYMBOL[item][2] for item in NXF_IDS)
FUNCTION_COUNT = len(ALL_FUNCTIONS)

if NXF_IDS != tuple(f"NXF-{index:03d}" for index in range(1, 73)):
    raise RuntimeError("PR355_NXF_RANGE_MISMATCH")
if FUNCTION_COUNT != 72 or len(set(ALL_FUNCTIONS)) != 72:
    raise RuntimeError("PR355_FUNCTION_OWNERSHIP_MISMATCH")

__all__ = [
    "ALL_FUNCTIONS",
    "FUNCTION_COUNT",
    "GROUPS",
    "NXF_IDS",
    "NXF_TO_SYMBOL",
]
