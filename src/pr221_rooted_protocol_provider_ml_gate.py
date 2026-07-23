"""PR-221 rooted protocol/provider/discovery/ML integrity gate.

This module is intentionally side-effect free. It validates materialized evidence
for the PR-221 data plane before later runtime code can claim that provider and
protocol data are safe to turn into executable opportunities or ML datasets.

It does not open network connections, call Solana RPC, parse secrets, construct
transactions, sign messages, or enable a sender.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence
import hashlib
import json
import re


SCHEMA_VERSION = "pr221.rooted-protocol-provider-ml-gate.v1"
ROADMAP_ID = "PR-221"

REQUIRED_DEPENDENCIES = ("PR-219", "PR-220")
REQUIRED_FINDINGS = frozenset(
    [
        "F-012",
        "F-013",
        "F-015",
        "F-016",
        "F-017",
        "F-022",
        "F-040",
        "F-042",
        "F-043",
        "F-044",
        "F-048",
        "F-053",
        "F-054",
        "F-055",
        "F-056",
        "F-057",
        "F-070",
        "F-131",
        "F-132",
        "F-133",
        "F-134",
        "F-135",
        "F-136",
        "F-175",
        "F-176",
        "F-177",
        "F-178",
        "F-179",
        "F-180",
        "F-181",
        "F-182",
        "F-183",
        "F-184",
        "F-185",
        "F-186",
        "F-229",
        "F-230",
        "F-231",
        "F-232",
        "F-233",
        "F-309",
        "F-310",
        "F-311",
        "F-313",
        "F-314",
        "F-315",
        "F-316",
        "F-317",
        "F-318",
        "F-319",
        "F-320",
        "F-321",
        "F-322",
        "F-323",
        "F-324",
        "F-325",
        "F-326",
        "F-327",
        "F-331",
        "F-332",
        "F-333",
        "F-334",
        "F-335",
        "F-336",
        "F-337",
        "F-338",
        "F-339",
        "F-340",
        "F-341",
        "F-342",
        "F-343",
        "F-344",
        "F-345",
        "F-346",
        "F-347",
        "F-348",
        "F-349",
        "F-350",
        "F-351",
        "F-352",
        "F-353",
        "F-354",
        "F-355",
        "F-356",
        "F-357",
        "F-358",
        "F-359",
        "F-367",
        "F-368",
        "F-369",
        "F-370",
        "F-371",
        "F-372",
        "F-373",
        "F-374",
        "F-375",
        "F-376",
        "F-377",
        "F-378",
        "F-379",
        "F-380",
        "F-381",
        "F-382",
        "F-383",
        "F-384",
        "F-385",
        "F-386",
        "F-400",
        "F-401",
        "F-402",
        "F-404",
    ]
)
REQUIRED_PROTOCOLS = frozenset(
    [
        "solana_rpc",
        "jupiter_swap_v2",
        "marginfi",
        "helius",
        "spl_token",
        "token_2022",
    ]
)
REQUIRED_DRILLS = frozenset(
    [
        "dns_rebinding",
        "private_ip_resolution",
        "redirect_escape",
        "oversized_json",
        "deep_json",
        "duplicate_json_keys",
        "nan_infinity",
        "secret_header_leak",
        "429_without_retry_after",
        "helius_duplicate",
        "helius_correction",
        "helius_gap",
        "temporal_leakage",
        "ood_inference",
    ]
)
_REQUIRED_JUPITER_FIELDS = frozenset(
    ["routePlan", "computeBudgetInstructions", "tipInstruction", "addressLookupTableAddresses"]
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class PR221GateReport:
    schema_version: str
    roadmap: str
    accepted: bool
    executable_opportunity_allowed: bool
    decision_dataset_allowed: bool
    provider_network_allowed: bool
    live_execution_allowed: bool
    signer_allowed: bool
    sender_allowed: bool
    blockers: tuple[str, ...]
    evidence_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "roadmap": self.roadmap,
            "accepted": self.accepted,
            "executable_opportunity_allowed": self.executable_opportunity_allowed,
            "decision_dataset_allowed": self.decision_dataset_allowed,
            "provider_network_allowed": self.provider_network_allowed,
            "live_execution_allowed": self.live_execution_allowed,
            "signer_allowed": self.signer_allowed,
            "sender_allowed": self.sender_allowed,
            "blockers": list(self.blockers),
            "evidence_hash": self.evidence_hash,
        }


def evaluate_pr221_gate(evidence: Mapping[str, Any]) -> PR221GateReport:
    blockers: list[str] = []

    if evidence.get("schema_version") != SCHEMA_VERSION:
        blockers.append("SCHEMA_VERSION_MISMATCH")
    if evidence.get("roadmap") != ROADMAP_ID:
        blockers.append("ROADMAP_MISMATCH")

    blockers.extend(_check_capabilities(evidence.get("capabilities", {})))
    blockers.extend(_check_dependencies(evidence.get("dependencies", {})))
    blockers.extend(_check_findings(evidence.get("finding_coverage", [])))
    blockers.extend(_check_materialized_refs(evidence.get("materialized_evidence", [])))
    blockers.extend(_check_protocol_attestation(evidence.get("protocol_attestation", {})))
    blockers.extend(_check_transport(evidence.get("transport", {})))
    blockers.extend(_check_endpoint_quota(evidence.get("endpoint_quota", {})))
    blockers.extend(_check_rooted_lineage(evidence.get("rooted_lineage", {})))
    blockers.extend(_check_jupiter(evidence.get("jupiter_v2", {})))
    blockers.extend(_check_helius(evidence.get("helius", {})))
    blockers.extend(_check_discovery(evidence.get("discovery", {})))
    blockers.extend(_check_opportunity_domain(evidence.get("opportunity_domain", {})))
    blockers.extend(_check_ml(evidence.get("ml_dataset", {})))
    blockers.extend(_check_drills(evidence.get("adversarial_drills", [])))

    accepted = not blockers
    return PR221GateReport(
        schema_version=SCHEMA_VERSION,
        roadmap=ROADMAP_ID,
        accepted=accepted,
        executable_opportunity_allowed=accepted,
        decision_dataset_allowed=accepted,
        provider_network_allowed=False,
        live_execution_allowed=False,
        signer_allowed=False,
        sender_allowed=False,
        blockers=tuple(blockers),
        evidence_hash=_stable_hash(evidence),
    )


def evaluate(evidence: Mapping[str, Any]) -> dict[str, Any]:
    return evaluate_pr221_gate(evidence).to_dict()


def _check_capabilities(capabilities: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    for name in (
        "provider_network_allowed",
        "live_execution_allowed",
        "signer_allowed",
        "sender_allowed",
        "private_key_material_allowed",
    ):
        if capabilities.get(name) is not False:
            blockers.append(f"FORBIDDEN_CAPABILITY_{name.upper()}")
    return blockers


def _check_dependencies(dependencies: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    for dep in REQUIRED_DEPENDENCIES:
        record = dependencies.get(dep, {})
        if record.get("accepted") is not True:
            blockers.append(f"DEPENDENCY_NOT_ACCEPTED_{dep}")
        if record.get("materialized_evidence") is not True:
            blockers.append(f"DEPENDENCY_NOT_MATERIALIZED_{dep}")
        if not _is_sha256(record.get("evidence_sha256")):
            blockers.append(f"DEPENDENCY_DIGEST_INVALID_{dep}")
    return blockers


def _check_findings(findings: Sequence[Any]) -> list[str]:
    got = {str(item) for item in findings}
    missing = sorted(REQUIRED_FINDINGS.difference(got))
    if missing:
        return [f"FINDING_COVERAGE_INCOMPLETE:{','.join(missing[:12])}"]
    return []


def _check_materialized_refs(refs: Sequence[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    if not refs:
        return ["NO_MATERIALIZED_EVIDENCE"]
    for idx, ref in enumerate(refs):
        prefix = f"MATERIALIZED_REF_{idx}"
        if ref.get("materialized") is not True:
            blockers.append(f"{prefix}_NOT_MATERIALIZED")
        if str(ref.get("path", "")).startswith(("/tmp/", "tests/", "docs/")):
            blockers.append(f"{prefix}_UNSAFE_PATH")
        if not _is_sha256(ref.get("sha256")):
            blockers.append(f"{prefix}_INVALID_DIGEST")
        if int(ref.get("size_bytes", 0)) <= 0:
            blockers.append(f"{prefix}_EMPTY")
    return blockers


def _check_protocol_attestation(attestation: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    protocols = set(attestation.get("protocols", []))
    missing = REQUIRED_PROTOCOLS.difference(protocols)
    if missing:
        blockers.append(f"PROTOCOL_ATTESTATION_MISSING:{','.join(sorted(missing))}")
    if attestation.get("materialized_contract_bytes") is not True:
        blockers.append("PROTOCOL_CONTRACT_BYTES_NOT_MATERIALIZED")
    if attestation.get("self_attested_claims_allowed") is not False:
        blockers.append("SELF_ATTESTED_PROTOCOL_CLAIMS_ALLOWED")
    if attestation.get("program_deployments_hashed") is not True:
        blockers.append("PROGRAM_DEPLOYMENTS_NOT_HASHED")
    if attestation.get("token2022_extensions_bound") is not True:
        blockers.append("TOKEN2022_EXTENSIONS_NOT_BOUND")
    if attestation.get("wsol_lifecycle_bound") is not True:
        blockers.append("WSOL_LIFECYCLE_NOT_BOUND")
    if not _is_sha256(attestation.get("release_contract_digest")):
        blockers.append("PROTOCOL_RELEASE_DIGEST_INVALID")
    return blockers


def _check_transport(transport: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    required_true = (
        "single_owner",
        "https_only",
        "host_allowlist_enforced",
        "dns_ip_revalidation",
        "private_ip_blocked",
        "redirect_policy_enforced",
        "ca_bundle_digest_required",
        "strict_json_semantics",
        "duplicate_json_key_rejection",
        "response_byte_limit_streamed",
        "json_depth_key_budget",
        "headers_redacted",
        "bounded_cancellation",
        "shared_session_lifecycle",
    )
    for name in required_true:
        if transport.get(name) is not True:
            blockers.append(f"TRANSPORT_{name.upper()}_MISSING")
    if int(transport.get("max_response_bytes", 0)) <= 0:
        blockers.append("TRANSPORT_RESPONSE_LIMIT_INVALID")
    if int(transport.get("max_json_depth", 0)) <= 0:
        blockers.append("TRANSPORT_JSON_DEPTH_INVALID")
    if int(transport.get("max_json_keys", 0)) <= 0:
        blockers.append("TRANSPORT_JSON_KEY_LIMIT_INVALID")
    return blockers


def _check_endpoint_quota(endpoint_quota: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    required_true = (
        "typed_endpoint_registry",
        "credential_scoped_quota",
        "account_plan_environment_generation_bound",
        "reservation_state_machine",
        "reserved_issued_completed_released",
        "idempotent_transitions",
        "cache_bounded",
        "cache_returns_immutable_copy",
        "cooldown_for_429_without_retry_after",
    )
    for name in required_true:
        if endpoint_quota.get(name) is not True:
            blockers.append(f"QUOTA_{name.upper()}_MISSING")
    return blockers


def _check_rooted_lineage(lineage: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    required_true = (
        "rpc_slot_before_after_provider_call",
        "min_context_slot_bound",
        "blockhash_window_bound",
        "genesis_cluster_identity_bound",
        "fork_skew_policy",
        "authoritative_backfill",
        "provider_response_hash_bound",
        "endpoint_credential_scope_bound",
    )
    for name in required_true:
        if lineage.get(name) is not True:
            blockers.append(f"LINEAGE_{name.upper()}_MISSING")
    if int(lineage.get("max_slot_skew", -1)) < 0:
        blockers.append("LINEAGE_SLOT_SKEW_INVALID")
    return blockers


def _check_jupiter(jupiter: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if jupiter.get("single_v2_adapter") is not True:
        blockers.append("JUPITER_SINGLE_V2_ADAPTER_MISSING")
    if jupiter.get("v1_legacy_removed_or_quarantined") is not True:
        blockers.append("JUPITER_V1_NOT_RETIRED")
    if jupiter.get("fabricated_context_slot_allowed") is not False:
        blockers.append("JUPITER_FABRICATED_CONTEXT_SLOT_ALLOWED")
    if jupiter.get("official_build_schema_pinned") is not True:
        blockers.append("JUPITER_BUILD_SCHEMA_NOT_PINNED")
    if jupiter.get("route_plan_validated") is not True:
        blockers.append("JUPITER_ROUTE_PLAN_NOT_VALIDATED")
    if jupiter.get("alt_addresses_bound") is not True:
        blockers.append("JUPITER_ALT_NOT_BOUND")
    if jupiter.get("tip_and_cu_policy_bound") is not True:
        blockers.append("JUPITER_TIP_CU_NOT_BOUND")
    fields = set(jupiter.get("accepted_response_fields", []))
    if not _REQUIRED_JUPITER_FIELDS.issubset(fields):
        blockers.append("JUPITER_REQUIRED_FIELDS_MISSING")
    if jupiter.get("negative_percent_or_bps_rejected") is not True:
        blockers.append("JUPITER_ROUTE_PERCENT_BPS_NOT_VALIDATED")
    return blockers


def _check_helius(helius: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    required_true = (
        "authenticated_ingress",
        "provider_delivery_id",
        "atomic_dedupe_audit",
        "bounded_retry",
        "correction_model",
        "rooted_gap_recovery",
        "webhook_is_hint_only",
    )
    for name in required_true:
        if helius.get(name) is not True:
            blockers.append(f"HELIUS_{name.upper()}_MISSING")
    if helius.get("bearer_only_empty_constraints_allowed") is not False:
        blockers.append("HELIUS_BEARER_ONLY_EMPTY_CONSTRAINTS_ALLOWED")
    return blockers


def _check_discovery(discovery: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    required_true = (
        "guaranteed_minimum_output_only",
        "route_continuity_required",
        "artifact_digest_bound",
        "freshness_amount_slot_coupled",
        "deterministic_value_risk_ordering",
        "request_cost_budget_per_cycle",
        "cancelled_child_tasks_joined",
        "failure_evidence_has_reason_status_retryability",
    )
    for name in required_true:
        if discovery.get(name) is not True:
            blockers.append(f"DISCOVERY_{name.upper()}_MISSING")
    if discovery.get("executable_from_discovery_only_response_allowed") is not False:
        blockers.append("DISCOVERY_ONLY_EXECUTABLE_ALLOWED")
    return blockers


def _check_opportunity_domain(domain: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    required_true = (
        "finite_numeric_types",
        "u64_base_unit_money",
        "canonical_deep_freeze",
        "provider_evidence_aware_identity",
        "bounded_queues",
        "expired_after_ranker_rejected",
        "documented_priority_tiebreak",
    )
    for name in required_true:
        if domain.get(name) is not True:
            blockers.append(f"OPPORTUNITY_{name.upper()}_MISSING")
    if domain.get("input_mint_equals_output_allowed") is not False:
        blockers.append("OPPORTUNITY_SELF_SWAP_ALLOWED")
    max_slippage_bps = int(domain.get("max_slippage_bps", -1))
    if not 0 <= max_slippage_bps < 10_000:
        blockers.append("OPPORTUNITY_SLIPPAGE_POLICY_INVALID")
    return blockers


def _check_ml(ml: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    required_true = (
        "no_temporal_leakage",
        "exact_label_event_provenance",
        "canonical_utc_timestamps",
        "atomic_dataset_manifest",
        "manifest_bound_to_exact_rows",
        "group_aware_splits",
        "embargo_validated",
        "minimum_sample_policy",
        "ood_gate",
        "deterministic_hash_between_hosts",
        "nested_object_float_validation",
    )
    for name in required_true:
        if ml.get(name) is not True:
            blockers.append(f"ML_{name.upper()}_MISSING")
    if int(ml.get("minimum_training_rows", 0)) < 100:
        blockers.append("ML_MINIMUM_SAMPLE_TOO_LOW")
    if ml.get("undefined_metrics_as_strings_allowed") is not False:
        blockers.append("ML_UNDEFINED_METRICS_AS_STRINGS_ALLOWED")
    return blockers


def _check_drills(drills: Sequence[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    by_name = {str(drill.get("name")): drill for drill in drills}
    missing = REQUIRED_DRILLS.difference(by_name)
    if missing:
        blockers.append(f"ADVERSARIAL_DRILLS_MISSING:{','.join(sorted(missing))}")
    for name, drill in by_name.items():
        if drill.get("target") != "installed_sender_free_runtime":
            blockers.append(f"DRILL_{name}_NOT_INSTALLED_RUNTIME")
        if drill.get("result") != "blocked_fail_closed":
            blockers.append(f"DRILL_{name}_DID_NOT_FAIL_CLOSED")
        if not _is_sha256(drill.get("evidence_sha256")):
            blockers.append(f"DRILL_{name}_DIGEST_INVALID")
    return blockers


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _stable_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
