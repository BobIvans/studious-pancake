"""Immutable PR-358 relation/service contract projections.

These types are research-only projections over canonical evidence/product owners.
They deliberately carry no signer, sender, wallet, billing, cloud-mutation, or
release authority.
"""
from __future__ import annotations

from dataclasses import asdict, field, is_dataclass, make_dataclass
import hashlib
import json
import re
from typing import Any, Mapping

EFFECT_BOUNDARY = {
    "production_ready": False,
    "live_enabled": False,
    "execution_right": False,
    "signer_access": False,
    "submission_access": False,
    "wallet_access": False,
    "remote_mutation": False,
    "automatic_promotion": False,
    "automatic_capital_increase": False,
    "customer_billing": False,
    "external_service_activation": False,
}
_SHA = re.compile(r"^[0-9a-f]{64}$")


class PR358ContractError(ValueError):
    """Stable fail-closed PR-358 contract error."""


def _normalize(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _normalize(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


CONTRACT_SCHEMAS = {'ConditionalRelationCard': ['relation_id', 'conditioning_variables', 'common_cause_candidates', 'clock_correction', 'conditional_test', 'alternative_graphs', 'refuters', 'downgrade_reason', 'causal_status'], 'EarlyWarningSequence': ['sequence_id', 'ordered_event_types', 'lag_distributions', 'target_event', 'lead_time_distribution', 'precision', 'recall', 'false_alarm_rate', 'regime_scope', 'counterexamples'], 'InvariantLawCandidate': ['law_id', 'expression_or_constraint', 'variables', 'units', 'economic_semantics', 'market_scope', 'parameterization', 'heldout_tests', 'counterexamples', 'status'], 'RelationAtlasScorecard': ['benchmark_id', 'discovery_fdr', 'oos_predictive_rate', 'multi_regime_stability', 'transfer_success_rate', 'counterexample_density', 'early_warning_metrics', 'data_cost', 'compute_cost', 'replication_rate', 'allowed_uses'], 'RelationAtlasSnapshot': ['snapshot_id', 'knowledge_cutoff', 'relation_ids', 'status_counts', 'market_coverage', 'blind_spots', 'stale_relations', 'falsified_relations', 'source_generations', 'hash'], 'RelationCandidate': ['relation_id', 'source_variables', 'target_variables', 'relation_family', 'direction', 'lag_or_horizon', 'conditioning_set', 'market_scope', 'regime_scope', 'method_id', 'discovery_cutoff', 'status', 'causal_claim=false', 'execution_right=false'], 'RelationCounterexample': ['counterexample_id', 'relation_id', 'market_state', 'episode_id', 'expected_relation', 'observed_violation', 'semantic_generation', 'retest_trigger', 'evidence_refs'], 'RelationEpisode': ['episode_id', 'pre_state_hash', 'trigger_event', 'trigger_available_at', 'reaction_window', 'linked_markets', 'observations', 'missingness', 'interference_cluster', 'label_available_at', 'outcome_status'], 'RelationEvidenceCard': ['relation_id', 'episode_ids', 'control_episode_ids', 'fit_period', 'heldout_period', 'effect_size', 'uncertainty', 'fdr_family', 'calibration_metrics', 'source_ablation', 'method_comparison', 'counterexample_refs', 'evidence_hash'], 'RelationStabilityCard': ['relation_id', 'windows', 'regimes', 'topology_generations', 'effect_path', 'half_life', 'sign_flips', 'breaks', 'requalification_due', 'allowed_scope'], 'RelationTransferCard': ['motif_id', 'source_markets', 'target_market', 'semantic_mapping', 'target_local_baseline', 'transfer_model', 'target_episode_budget', 'gain', 'negative_transfer', 'verdict'], 'TailRelationCard': ['relation_id', 'tail_definition', 'copula_or_tail_model', 'upper_tail', 'lower_tail', 'conditional_tail_metrics', 'stress_periods', 'heldout_metrics', 'uncertainty'], 'AgentTrustCard': ['agent_identity_ref', 'capability_claims', 'validation_refs', 'feedback_count', 'feedback_diversity', 'reputation_features', 'sybil_risk', 'stake_or_proof_refs', 'scope', 'trust_not_authority=true'], 'ConfidentialServiceCard': ['service_id', 'confidential_input_class', 'reveal_policy', 'trusted_components', 'attestation_or_protocol_refs', 'leakage_metric', 'latency_overhead', 'consumer_quality', 'fallback_public_path'], 'KeeperJobMarketCard': ['job_family', 'authorization_scope', 'state_trigger', 'worst_debit', 'service_fee', 'completion_rate', 'failure_cost', 'repeatability', 'consumer_value_proxy', 'simulation_only=true'], 'MachinePaymentCard': ['protocol_version', 'network', 'asset', 'payment_mode', 'single_or_batch', 'service_price', 'settlement_overhead', 'latency', 'facilitator_cost', 'failure_rate', 'break_even_calls'], 'MarketScienceExchangeScorecard': ['benchmark_id', 'service_ids', 'consumer_tasks', 'service_quality', 'sla', 'evidence_integrity', 'trust_metrics', 'payment_overhead', 'unit_economics', 'abuse_tail_loss', 'replication', 'allowed_uses'], 'MarketScienceServiceOffer': ['service_id', 'service_family', 'provider_id', 'input_schema', 'output_schema', 'evidence_tier', 'freshness_policy', 'sla', 'price_model', 'access_scope', 'distribution_rights', 'privacy_class', 'validation_refs', 'live_effect=false'], 'ServiceEconomicsCard': ['service_id', 'fixed_cost', 'marginal_cost', 'compute_cost', 'source_cost', 'verification_cost', 'support_cost', 'observed_demand', 'price_trials', 'subsidy', 'gross_margin_research', 'break_even_volume'], 'ServiceFulfillmentReceipt': ['request_id', 'service_id', 'provider_id', 'artifact_hash', 'evidence_refs', 'started_at', 'completed_at', 'sla_status', 'cost_vector', 'payment_state', 'consumer_feedback_ref', 'actual_market_outcome_claimed=false'], 'ServiceRequest': ['request_id', 'consumer_id', 'service_id', 'input_refs', 'deadline', 'max_price', 'required_evidence_tier', 'privacy_requirement', 'payment_method', 'request_scope', 'execution_right=false'], 'SolverMarketEpisode': ['episode_id', 'intent_spec', 'auction_type', 'available_liquidity', 'solver_strategies', 'quotes', 'fill_attempts', 'user_output', 'gas_and_inventory_cost', 'fade_or_failure', 'winner', 'evidence_refs'], 'SponsorshipEconomicsCard': ['provider', 'fee_asset', 'payment_asset', 'network_fee', 'account_creation_cost', 'conversion_cost', 'failure_cost', 'abuse_loss', 'reserve_requirement', 'service_fee', 'subsidy', 'stress_results'], 'VerifiableSimulationOffer': ['offer_id', 'candidate_hash', 'state_root_or_snapshot', 'transaction_or_plan_hash', 'simulator_version', 'balance_delta_commitment', 'fee_commitment', 'proof_or_replay_method', 'privacy_policy', 'verification_cost']}

_FALSE_FLAGS = {
    "execution_right",
    "live_effect",
    "actual_market_outcome_claimed",
    "causal_claim",
}
_TRUE_FLAGS = {"simulation_only", "trust_not_authority"}


def _field_name(raw: str) -> str:
    return raw.split("=", 1)[0].replace("/", "_").replace(" ", "_").replace("-", "_")


def _post_init(self: Any) -> None:
    for name in _FALSE_FLAGS:
        if hasattr(self, name) and bool(getattr(self, name)):
            raise PR358ContractError(f"PR358_FORBIDDEN_TRUE_FLAG:{name}")
    for name in _TRUE_FLAGS:
        if hasattr(self, name) and not bool(getattr(self, name)):
            raise PR358ContractError(f"PR358_REQUIRED_TRUE_FLAG:{name}")


_CONTRACT_TYPES: dict[str, type[Any]] = {}
for _name, _raw_fields in CONTRACT_SCHEMAS.items():
    _names = tuple(dict.fromkeys(_field_name(item) for item in _raw_fields))
    _spec = []
    for _field in _names:
        if _field in _FALSE_FLAGS:
            _spec.append((_field, object, field(default=False)))
        elif _field in _TRUE_FLAGS:
            _spec.append((_field, object, field(default=True)))
        else:
            _spec.append((_field, object))
    _CONTRACT_TYPES[_name] = make_dataclass(
        _name,
        _spec,
        frozen=True,
        slots=True,
        namespace={"__post_init__": _post_init},
    )


def contract_type(name: str) -> type[Any]:
    try:
        return _CONTRACT_TYPES[name]
    except KeyError as exc:
        raise PR358ContractError(f"PR358_UNKNOWN_CONTRACT:{name}") from exc


def assert_sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        raise PR358ContractError(f"PR358_SHA256_REQUIRED:{field_name}")
    return value
