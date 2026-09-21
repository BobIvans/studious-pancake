"""Concrete default-off PR-355 MarketPack adapter bindings.

These bindings connect each MarketPack to existing instrument/data/rights/target
owners without creating a second journal, graph, evaluator, signer, sender or
release authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .evidence_native_core import EvidenceNativeError


@dataclass(frozen=True, slots=True)
class MarketPackAdapterBinding:
    pack_id: str
    mode: str
    instrument_owner: str
    data_owner: str
    rights_owner: str
    target_owner: str
    evidence_owner: str
    blockers: tuple[str, ...]
    state: str = "DISABLED"
    live_enabled: bool = False
    signer_access: bool = False
    submission_access: bool = False
    remote_mutation: bool = False

    def __post_init__(self) -> None:
        if not self.pack_id.startswith("MP-N"):
            raise EvidenceNativeError("MARKETPACK_BINDING_ID_INVALID")
        if self.state != "DISABLED":
            raise EvidenceNativeError("MARKETPACK_BINDING_MUST_BE_DISABLED")
        if (
            self.live_enabled
            or self.signer_access
            or self.submission_access
            or self.remote_mutation
        ):
            raise EvidenceNativeError("MARKETPACK_BINDING_EFFECT_FORBIDDEN")
        for owner in (
            self.instrument_owner,
            self.data_owner,
            self.rights_owner,
            self.target_owner,
            self.evidence_owner,
        ):
            if not owner or ":" not in owner:
                raise EvidenceNativeError("MARKETPACK_OWNER_SYMBOL_REQUIRED")


_BINDINGS: Mapping[str, MarketPackAdapterBinding] = {
    "MP-N01": MarketPackAdapterBinding(
        pack_id="MP-N01",
        mode="read_only_replay",
        instrument_owner="src.mechanism_discovery.claims:define_cashflow_stream",
        data_owner="src.mechanism_discovery.boros:materialize_boros_fixture_state",
        rights_owner="src.mechanism_discovery.claims:qualify_cashflow_identity",
        target_owner="src.mechanism_discovery.boros:run_boros_fixture_vertical",
        evidence_owner="src.mechanism_discovery.research_receipt:bind_receipt_to_evidence_ledger",
        blockers=("BOROS_PRIMARY_SOURCE_PIN_ENTITLEMENT_NOT_MATERIALIZED",),
    ),
    "MP-N02": MarketPackAdapterBinding(
        pack_id="MP-N02",
        mode="fork_and_replay_only",
        instrument_owner="src.mechanism_discovery.liquidity_shape:define_liquidity_shape",
        data_owner="src.mechanism_discovery.hook_native:ingest_v4_hook_registry",
        rights_owner="src.mechanism_discovery.mechanism_compiler:infer_rights_obligations_timing",
        target_owner="src.mechanism_discovery.liquidity_shape:compare_hybrid_execution_paths",
        evidence_owner="src.strategy_evolution.residual_discovery:update_anomaly_coverage_registry",
        blockers=(
            "HOT_DEPLOYMENT_PIN_NOT_MATERIALIZED",
            "BUNNI_REFERENCE_ONLY_QUARANTINED",
        ),
    ),
    "MP-N03": MarketPackAdapterBinding(
        pack_id="MP-N03",
        mode="read_only_shadow",
        instrument_owner="src.mechanism_discovery.programmable_cash:register_programmable_cash_asset",
        data_owner="src.mechanism_discovery.programmable_cash:read_mint_redeem_capacity",
        rights_owner="src.mechanism_discovery.programmable_cash:qualify_redemption_eligibility",
        target_owner="src.mechanism_discovery.programmable_cash:detect_extension_parity_residual",
        evidence_owner="src.strategy_evolution.residual_discovery:update_anomaly_coverage_registry",
        blockers=("M0_DEPLOYMENT_SCHEMA_AND_ENTITLEMENT_NOT_MATERIALIZED",),
    ),
    "MP-N04": MarketPackAdapterBinding(
        pack_id="MP-N04",
        mode="research_only",
        instrument_owner="src.mechanism_discovery.programmable_cash:decompose_synthetic_dollar_backing",
        data_owner="src.mechanism_discovery.operationalize:capture_evo_point_in_time_corpus",
        rights_owner="src.mechanism_discovery.programmable_cash:qualify_redemption_eligibility",
        target_owner="src.mechanism_discovery.programmable_cash:detect_extension_parity_residual",
        evidence_owner="src.strategy_evolution.residual_discovery:update_anomaly_coverage_registry",
        blockers=("ETHENA_BACKING_CUSTODY_ELIGIBILITY_SOURCE_NOT_MATERIALIZED",),
    ),
    "MP-N05": MarketPackAdapterBinding(
        pack_id="MP-N05",
        mode="research_only",
        instrument_owner="src.mechanism_discovery.rwa:register_rwa_instrument_rights",
        data_owner="src.mechanism_discovery.rwa:ingest_nav_revision_history",
        rights_owner="src.mechanism_discovery.rwa:qualify_rwa_access_path",
        target_owner="src.mechanism_discovery.rwa:detect_rwa_nav_basis",
        evidence_owner="src.strategy_evolution.residual_discovery:update_anomaly_coverage_registry",
        blockers=("RWA_NAV_SESSION_CUSTODY_ENTITLEMENT_NOT_MATERIALIZED",),
    ),
    "MP-N06": MarketPackAdapterBinding(
        pack_id="MP-N06",
        mode="fork_read_only",
        instrument_owner="src.mechanism_discovery.shared_credit:map_hub_spoke_liquidity",
        data_owner="src.mechanism_discovery.shared_credit:simulate_cross_spoke_utilization",
        rights_owner="src.mechanism_discovery.shared_credit:qualify_shared_credit_route",
        target_owner="src.mechanism_discovery.shared_credit:detect_hub_spoke_basis",
        evidence_owner="src.strategy_evolution.residual_discovery:update_anomaly_coverage_registry",
        blockers=("AAVE_V4_EXACT_DEPLOYMENT_AND_FORK_STATE_NOT_MATERIALIZED",),
    ),
    "MP-N07": MarketPackAdapterBinding(
        pack_id="MP-N07",
        mode="testnet_or_zero_cost_mock",
        instrument_owner="src.mechanism_discovery.research_resources:register_paid_research_resource",
        data_owner="src.mechanism_discovery.research_resources:discover_paid_resource",
        rights_owner="src.mechanism_discovery.research_resources:authorize_bounded_resource_purchase",
        target_owner="src.mechanism_discovery.research_resources:score_information_value_after_payment",
        evidence_owner="src.mechanism_discovery.research_resources:reconcile_resource_payment",
        blockers=("REAL_PRODUCTION_PAYMENT_FORBIDDEN",),
    ),
    "MP-N08": MarketPackAdapterBinding(
        pack_id="MP-N08",
        mode="offline_only",
        instrument_owner="src.mechanism_discovery.research_receipt:build_research_receipt_manifest",
        data_owner="src.mechanism_discovery.research_receipt:replay_receipt_computation",
        rights_owner="src.mechanism_discovery.research_receipt:generate_optional_computation_proof",
        target_owner="src.mechanism_discovery.research_receipt:verify_computation_proof",
        evidence_owner="src.mechanism_discovery.research_receipt:bind_receipt_to_evidence_ledger",
        blockers=("PRODUCTION_PROOF_BACKEND_NOT_QUALIFIED",),
    ),
    "MP-N09": MarketPackAdapterBinding(
        pack_id="MP-N09",
        mode="offline_only",
        instrument_owner="src.mechanism_discovery.incident_admission:ingest_protocol_incident",
        data_owner="src.mechanism_discovery.incident_admission:build_adversarial_mechanism_states",
        rights_owner="src.mechanism_discovery.incident_admission:quarantine_vulnerable_deployment",
        target_owner="src.mechanism_discovery.incident_admission:gate_mechanism_admission_on_security",
        evidence_owner="src.mechanism_discovery.incident_admission:derive_incident_invariant_tests",
        blockers=("BUNNI_INCIDENT_CORPUS_REFERENCE_ONLY",),
    ),
}


def build_marketpack_binding(pack_id: str) -> MarketPackAdapterBinding:
    try:
        return _BINDINGS[pack_id]
    except KeyError as exc:
        raise EvidenceNativeError("MARKETPACK_BINDING_UNKNOWN") from exc


def all_marketpack_bindings() -> tuple[MarketPackAdapterBinding, ...]:
    return tuple(_BINDINGS[pack_id] for pack_id in sorted(_BINDINGS))


__all__ = [
    "MarketPackAdapterBinding",
    "all_marketpack_bindings",
    "build_marketpack_binding",
]
