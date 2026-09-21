"""MEGA8-05 signer-free autonomous R&D and statistical intelligence.

The package is an offline/default-off research layer for NF-641..NF-704.  It
does not own runtime admission, signing, submission, settlement, or capital
promotion.
"""

from .base import Disposition, ResearchArtifact
from .pr239_upstream import (
    discover_upstream_release_candidates,
    extract_candidate_symbols,
    publish_upstream_research_dossier,
    rank_reuse_opportunity,
)
from .pr240_codegen import (
    generate_abi_read_adapter,
    generate_idl_account_decoder,
    generate_move_resource_decoder,
    validate_generated_adapter,
)
from .pr241_adapter_sdk import (
    build_golden_vector_pack,
    define_adapter_conformance_contract,
    publish_adapter_qualification,
    run_adapter_differential_suite,
)
from .pr242_discovery import (
    collect_promotion_evidence,
    discover_unknown_deployment,
    promote_discovered_capability,
    quarantine_unknown_market,
)
from .pr243_semantics import (
    infer_account_relationships,
    infer_shared_resource_dependencies,
    reconstruct_cpi_call_graph,
    validate_inferred_semantics,
)
from .pr244_license import (
    classify_copy_eligibility,
    enforce_source_reuse_policy,
    generate_attribution_bundle,
    scan_license_surface,
)
from .pr245_preregistration import (
    bind_dataset_cutoff,
    freeze_analysis_plan,
    publish_preregistered_experiment,
    register_research_hypothesis,
)
from .pr246_multiple_testing import (
    apply_multiple_test_correction,
    enumerate_hypothesis_family,
    estimate_false_discovery_rate,
    gate_discovery_claim,
)
from .pr247_labels import (
    audit_selection_bias,
    label_missingness_mechanism,
    model_observation_selection,
    weight_selective_samples,
)
from .pr248_entity import (
    link_wallet_program_relationships,
    publish_entity_graph,
    resolve_asset_entities,
    resolve_protocol_entities,
)
from .pr249_factors import (
    detect_factor_residual,
    estimate_factor_exposures,
    fit_dynamic_factor_model,
    update_online_covariance,
)
from .pr250_stat_arb import (
    discover_cointegrated_baskets,
    estimate_hedge_vector,
    model_mean_reversion_half_life,
    qualify_stat_arb_basket,
)
from .pr251_regimes import (
    archive_regime_transition,
    detect_structural_break,
    infer_market_regime,
    route_policy_by_regime,
)
from .pr252_leadlag import (
    build_information_flow_graph,
    estimate_multiscale_lead_lag,
    promote_predictive_link,
    test_lead_lag_stability,
)
from .pr253_flow import (
    classify_wallet_flow,
    estimate_flow_toxicity,
    infer_meta_order,
    route_flow_signal,
)
from .pr254_scam import (
    detect_liquidity_withdrawal_risk,
    enforce_dynamic_asset_quarantine,
    monitor_authority_mutations,
    score_honeypot_or_rug_behavior,
)

__all__ = [
    "Disposition",
    "ResearchArtifact",
    "apply_multiple_test_correction",
    "archive_regime_transition",
    "audit_selection_bias",
    "bind_dataset_cutoff",
    "build_golden_vector_pack",
    "build_information_flow_graph",
    "classify_copy_eligibility",
    "classify_wallet_flow",
    "collect_promotion_evidence",
    "detect_factor_residual",
    "detect_liquidity_withdrawal_risk",
    "detect_structural_break",
    "define_adapter_conformance_contract",
    "discover_cointegrated_baskets",
    "discover_unknown_deployment",
    "discover_upstream_release_candidates",
    "enforce_dynamic_asset_quarantine",
    "enforce_source_reuse_policy",
    "enumerate_hypothesis_family",
    "estimate_factor_exposures",
    "estimate_false_discovery_rate",
    "estimate_flow_toxicity",
    "estimate_hedge_vector",
    "estimate_multiscale_lead_lag",
    "extract_candidate_symbols",
    "fit_dynamic_factor_model",
    "freeze_analysis_plan",
    "gate_discovery_claim",
    "generate_abi_read_adapter",
    "generate_attribution_bundle",
    "generate_idl_account_decoder",
    "generate_move_resource_decoder",
    "infer_account_relationships",
    "infer_market_regime",
    "infer_meta_order",
    "infer_shared_resource_dependencies",
    "label_missingness_mechanism",
    "link_wallet_program_relationships",
    "model_mean_reversion_half_life",
    "model_observation_selection",
    "monitor_authority_mutations",
    "promote_discovered_capability",
    "promote_predictive_link",
    "publish_adapter_qualification",
    "publish_entity_graph",
    "publish_preregistered_experiment",
    "publish_upstream_research_dossier",
    "qualify_stat_arb_basket",
    "quarantine_unknown_market",
    "rank_reuse_opportunity",
    "reconstruct_cpi_call_graph",
    "register_research_hypothesis",
    "resolve_asset_entities",
    "resolve_protocol_entities",
    "route_flow_signal",
    "route_policy_by_regime",
    "run_adapter_differential_suite",
    "scan_license_surface",
    "score_honeypot_or_rug_behavior",
    "test_lead_lag_stability",
    "update_online_covariance",
    "validate_generated_adapter",
    "validate_inferred_semantics",
    "weight_selective_samples",
]
