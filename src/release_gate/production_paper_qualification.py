"""Production paper qualification contract for MEGA-PR-02.

This module is intentionally sender-free and offline.  It defines the release
qualification boundary that must be satisfied after MEGA-PR-01 and before any
paper-ready promotion.  It does not contact providers, build artifacts, load
secrets, sign messages, or submit transactions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Mapping

SCHEMA_VERSION = "release.production-paper-qualification.v1"
PAPER_READY_ALLOWED = True
LIVE_EXECUTION_ALLOWED = False
SIGNER_ALLOWED = False
SENDER_ALLOWED = False

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=-]{0,159}$")
_FULL_ACTION_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

REQUIRED_PROTOCOLS = (
    "solana-v0-rpc",
    "jupiter-swap",
    "marginfi-v2",
    "kamino-klend",
)
REQUIRED_CHAOS_SCENARIOS = (
    "rpc-split-brain",
    "stale-oracle",
    "provider-schema-drift",
    "rate-limit",
    "db-lock",
    "full-disk",
    "restart",
    "clock-jump",
    "webhook-replay",
)


class QualificationEvidenceError(ValueError):
    """Raised when MEGA-PR-02 evidence is malformed."""


class QualificationBlocker(StrEnum):
    """Stable fail-closed blocker codes."""

    MEGA_PR_01_NOT_ACCEPTED = "MEGA_PR_01_NOT_ACCEPTED"
    PROTOCOL_SET_INCOMPLETE = "PROTOCOL_SET_INCOMPLETE"
    PROTOCOL_CONFORMANCE_INCOMPLETE = "PROTOCOL_CONFORMANCE_INCOMPLETE"
    JUPITER_CONTRACT_AMBIGUOUS = "JUPITER_CONTRACT_AMBIGUOUS"
    OPTIONAL_PROVIDER_ADMITTED_WITHOUT_EVIDENCE = (
        "OPTIONAL_PROVIDER_ADMITTED_WITHOUT_EVIDENCE"
    )
    MESSAGE_SIMULATION_MISMATCH = "MESSAGE_SIMULATION_MISMATCH"
    MESSAGE_MUTABLE_AFTER_SIMULATION = "MESSAGE_MUTABLE_AFTER_SIMULATION"
    INSTRUCTION_OR_ACCOUNT_PROOF_INCOMPLETE = (
        "INSTRUCTION_OR_ACCOUNT_PROOF_INCOMPLETE"
    )
    ECONOMIC_PROOF_INCOMPLETE = "ECONOMIC_PROOF_INCOMPLETE"
    RELEASE_IDENTITY_MISMATCH = "RELEASE_IDENTITY_MISMATCH"
    RELEASE_BUILD_NOT_HERMETIC = "RELEASE_BUILD_NOT_HERMETIC"
    SUPPLY_CHAIN_NOT_PINNED = "SUPPLY_CHAIN_NOT_PINNED"
    ARTIFACT_ATTESTATION_INCOMPLETE = "ARTIFACT_ATTESTATION_INCOMPLETE"
    SANDBOX_NOT_ENFORCED = "SANDBOX_NOT_ENFORCED"
    SECRET_OR_OPERATOR_POLICY_INCOMPLETE = "SECRET_OR_OPERATOR_POLICY_INCOMPLETE"
    SOAK_TOO_SHORT = "SOAK_TOO_SHORT"
    SOAK_SYNTHETIC_OR_NOT_RELEASE_BOUND = "SOAK_SYNTHETIC_OR_NOT_RELEASE_BOUND"
    CHAOS_MATRIX_INCOMPLETE = "CHAOS_MATRIX_INCOMPLETE"
    SLO_OR_TERMINAL_INVARIANTS_FAILED = "SLO_OR_TERMINAL_INVARIANTS_FAILED"
    PROMOTION_EVIDENCE_NOT_INDEPENDENT = "PROMOTION_EVIDENCE_NOT_INDEPENDENT"
    LIVE_OR_SIGNER_SURFACE_REACHABLE = "LIVE_OR_SIGNER_SURFACE_REACHABLE"


@dataclass(frozen=True, slots=True)
class MaterializedArtifact:
    """Content-addressed evidence created by a named producer."""

    path: str
    sha256: str
    size_bytes: int
    producer_id: str
    media_type: str

    def __post_init__(self) -> None:
        _relative_path(self.path, "path")
        _sha256(self.sha256, "sha256")
        _positive_int(self.size_bytes, "size_bytes")
        _identifier(self.producer_id, "producer_id")
        _identifier(self.media_type, "media_type")


@dataclass(frozen=True, slots=True)
class ProtocolConformance:
    """Credentialed conformance for one admitted protocol generation."""

    protocol_id: str
    contract_generation: str
    credentialed_probe: MaterializedArtifact
    golden_fixtures: MaterializedArtifact
    negative_fixtures: MaterializedArtifact
    schema_pinned: bool
    program_and_account_identity_verified: bool
    drift_detection_materialized: bool
    supported_combinations_nonempty: bool = True

    def __post_init__(self) -> None:
        _identifier(self.protocol_id, "protocol_id")
        _identifier(self.contract_generation, "contract_generation")


@dataclass(frozen=True, slots=True)
class ExactMessageProof:
    """Exact compiled-message, simulation and economics binding."""

    compiled_message_sha256: str
    simulated_message_sha256: str
    transaction_proof: MaterializedArtifact
    simulation_result: MaterializedArtifact
    economics_result: MaterializedArtifact
    instruction_order_verified: bool
    program_allowlist_verified: bool
    account_metas_verified: bool
    signer_writable_flags_verified: bool
    compute_budget_verified: bool
    blockhash_validity_verified: bool
    mutation_after_simulation_impossible: bool
    total_fees_rent_and_tips_reserved: bool
    slippage_bound_verified: bool
    flash_repayment_verified: bool
    minimum_profit_verified: bool

    def __post_init__(self) -> None:
        _sha256(self.compiled_message_sha256, "compiled_message_sha256")
        _sha256(self.simulated_message_sha256, "simulated_message_sha256")


@dataclass(frozen=True, slots=True)
class HermeticReleaseEvidence:
    """Release identity, build and supply-chain proof."""

    source_commit: str
    source_tree_sha256: str
    wheel_sha256: str
    image_sha256: str
    config_sha256: str
    provider_contracts_sha256: str
    qualification_manifest: MaterializedArtifact
    sbom: MaterializedArtifact
    provenance: MaterializedArtifact
    artifact_signature: MaterializedArtifact
    clean_source_tree: bool
    network_disabled_build: bool
    offline_hash_locked_wheelhouse: bool
    reproducible_build_verified: bool
    github_actions_refs: tuple[str, ...]
    docker_base_image_digest: str
    wheel_image_surface_equal: bool

    def __post_init__(self) -> None:
        if not _FULL_ACTION_SHA_RE.fullmatch(self.source_commit):
            raise QualificationEvidenceError(
                "source_commit must be a 40-character lowercase git SHA"
            )
        for value, name in (
            (self.source_tree_sha256, "source_tree_sha256"),
            (self.wheel_sha256, "wheel_sha256"),
            (self.image_sha256, "image_sha256"),
            (self.config_sha256, "config_sha256"),
            (self.provider_contracts_sha256, "provider_contracts_sha256"),
            (self.docker_base_image_digest, "docker_base_image_digest"),
        ):
            _sha256(value, name)
        if not isinstance(self.github_actions_refs, tuple):
            raise QualificationEvidenceError("github_actions_refs must be a tuple")
        for value in self.github_actions_refs:
            if not _FULL_ACTION_SHA_RE.fullmatch(value):
                raise QualificationEvidenceError(
                    "every GitHub Action reference must be a full commit SHA"
                )


@dataclass(frozen=True, slots=True)
class SandboxEvidence:
    """Measured container and operator-control enforcement."""

    runtime_test_report: MaterializedArtifact
    apparmor_profile: MaterializedArtifact
    seccomp_profile: MaterializedArtifact
    egress_policy: MaterializedArtifact
    non_root_runtime: bool
    read_only_root_filesystem: bool
    apparmor_loaded_and_hash_verified: bool
    seccomp_loaded_and_hash_verified: bool
    denied_write_capability_and_egress_tests_passed: bool
    egress_destination_port_dns_allowlist_enforced: bool
    secrets_from_files_or_manager_only: bool
    plaintext_secret_placeholders_absent: bool
    secret_rotation_drill_passed: bool
    operator_plane_authenticated: bool
    operator_rbac_enforced: bool
    audit_log_durable: bool
    pause_drain_kill_switch_tested: bool
    break_glass_procedure_tested: bool


@dataclass(frozen=True, slots=True)
class SoakQualificationEvidence:
    """Release-bound non-synthetic 72-hour paper qualification."""

    soak_report: MaterializedArtifact
    slo_report: MaterializedArtifact
    chaos_report: MaterializedArtifact
    operator_drill_report: MaterializedArtifact
    independent_review: MaterializedArtifact
    duration_hours: int
    release_wheel_sha256: str
    release_image_sha256: str
    release_config_sha256: str
    release_provider_contracts_sha256: str
    non_synthetic_streaming_data: bool
    real_provider_data_plane: bool
    synthetic_contamination_count: int
    lost_intents: int
    duplicate_intents: int
    unexplained_terminal_states: int
    accepted_cycles_have_complete_causal_economic_chain: bool
    required_chaos_scenarios_completed: tuple[str, ...]
    provider_availability_slo_met: bool
    rooted_freshness_slo_met: bool
    latency_slo_met: bool
    queue_and_cycle_slo_met: bool
    reconciliation_slo_met: bool
    resource_profiles_materialized: bool
    alert_routing_and_runbooks_drilled: bool
    evidence_signed_and_immutable: bool
    independently_reviewed: bool

    def __post_init__(self) -> None:
        _non_negative_int(self.duration_hours, "duration_hours")
        for digest, digest_name in (
            (self.release_wheel_sha256, "release_wheel_sha256"),
            (self.release_image_sha256, "release_image_sha256"),
            (self.release_config_sha256, "release_config_sha256"),
            (
                self.release_provider_contracts_sha256,
                "release_provider_contracts_sha256",
            ),
        ):
            _sha256(digest, digest_name)
        for count, count_name in (
            (self.synthetic_contamination_count, "synthetic_contamination_count"),
            (self.lost_intents, "lost_intents"),
            (self.duplicate_intents, "duplicate_intents"),
            (self.unexplained_terminal_states, "unexplained_terminal_states"),
        ):
            _non_negative_int(count, count_name)
        if not isinstance(self.required_chaos_scenarios_completed, tuple):
            raise QualificationEvidenceError(
                "required_chaos_scenarios_completed must be a tuple"
            )


@dataclass(frozen=True, slots=True)
class ProductionPaperQualificationEvidence:
    """Complete MEGA-PR-02 qualification envelope."""

    mega_pr_01_accepted: bool
    mega_pr_01_report_sha256: str
    protocols: tuple[ProtocolConformance, ...]
    optional_provider_ids: tuple[str, ...]
    optional_providers_admitted: tuple[str, ...]
    jupiter_contract_generations: tuple[str, ...]
    exact_message: ExactMessageProof
    release: HermeticReleaseEvidence
    sandbox: SandboxEvidence
    soak: SoakQualificationEvidence
    live_execution_reachable: bool = False
    signer_reachable: bool = False
    sender_reachable: bool = False

    def __post_init__(self) -> None:
        _sha256(self.mega_pr_01_report_sha256, "mega_pr_01_report_sha256")
        if not isinstance(self.protocols, tuple):
            raise QualificationEvidenceError("protocols must be a tuple")
        if not isinstance(self.optional_provider_ids, tuple):
            raise QualificationEvidenceError("optional_provider_ids must be a tuple")
        if not isinstance(self.optional_providers_admitted, tuple):
            raise QualificationEvidenceError(
                "optional_providers_admitted must be a tuple"
            )
        if not isinstance(self.jupiter_contract_generations, tuple):
            raise QualificationEvidenceError(
                "jupiter_contract_generations must be a tuple"
            )


@dataclass(frozen=True, slots=True)
class ProductionPaperQualificationReport:
    """Deterministic MEGA-PR-02 qualification result."""

    schema_version: str
    ready: bool
    blockers: tuple[str, ...]
    evidence_hash: str
    paper_ready_allowed: bool
    live_execution_allowed: bool = LIVE_EXECUTION_ALLOWED
    signer_allowed: bool = SIGNER_ALLOWED
    sender_allowed: bool = SENDER_ALLOWED

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ready": self.ready,
            "blockers": list(self.blockers),
            "evidence_hash": self.evidence_hash,
            "paper_ready_allowed": self.paper_ready_allowed,
            "live_execution_allowed": self.live_execution_allowed,
            "signer_allowed": self.signer_allowed,
            "sender_allowed": self.sender_allowed,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def evaluate_production_paper_qualification(
    evidence: ProductionPaperQualificationEvidence,
) -> ProductionPaperQualificationReport:
    """Evaluate the sender-free production paper qualification boundary."""

    blockers: list[QualificationBlocker] = []

    if not evidence.mega_pr_01_accepted:
        blockers.append(QualificationBlocker.MEGA_PR_01_NOT_ACCEPTED)

    protocol_map = {item.protocol_id: item for item in evidence.protocols}
    if set(protocol_map) != set(REQUIRED_PROTOCOLS):
        blockers.append(QualificationBlocker.PROTOCOL_SET_INCOMPLETE)
    for protocol_id in REQUIRED_PROTOCOLS:
        item = protocol_map.get(protocol_id)
        if item is None:
            continue
        if not (
            item.schema_pinned
            and item.program_and_account_identity_verified
            and item.drift_detection_materialized
            and item.supported_combinations_nonempty
        ):
            blockers.append(QualificationBlocker.PROTOCOL_CONFORMANCE_INCOMPLETE)

    if len(set(evidence.jupiter_contract_generations)) != 1:
        blockers.append(QualificationBlocker.JUPITER_CONTRACT_AMBIGUOUS)
    admitted_optional = set(evidence.optional_providers_admitted)
    if admitted_optional - set(evidence.optional_provider_ids):
        blockers.append(
            QualificationBlocker.OPTIONAL_PROVIDER_ADMITTED_WITHOUT_EVIDENCE
        )

    exact = evidence.exact_message
    if exact.compiled_message_sha256 != exact.simulated_message_sha256:
        blockers.append(QualificationBlocker.MESSAGE_SIMULATION_MISMATCH)
    if not exact.mutation_after_simulation_impossible:
        blockers.append(QualificationBlocker.MESSAGE_MUTABLE_AFTER_SIMULATION)
    if not all(
        (
            exact.instruction_order_verified,
            exact.program_allowlist_verified,
            exact.account_metas_verified,
            exact.signer_writable_flags_verified,
            exact.compute_budget_verified,
            exact.blockhash_validity_verified,
        )
    ):
        blockers.append(
            QualificationBlocker.INSTRUCTION_OR_ACCOUNT_PROOF_INCOMPLETE
        )
    if not all(
        (
            exact.total_fees_rent_and_tips_reserved,
            exact.slippage_bound_verified,
            exact.flash_repayment_verified,
            exact.minimum_profit_verified,
        )
    ):
        blockers.append(QualificationBlocker.ECONOMIC_PROOF_INCOMPLETE)

    release = evidence.release
    soak = evidence.soak
    if (
        soak.release_wheel_sha256 != release.wheel_sha256
        or soak.release_image_sha256 != release.image_sha256
        or soak.release_config_sha256 != release.config_sha256
        or soak.release_provider_contracts_sha256
        != release.provider_contracts_sha256
    ):
        blockers.append(QualificationBlocker.RELEASE_IDENTITY_MISMATCH)
    if not all(
        (
            release.clean_source_tree,
            release.network_disabled_build,
            release.offline_hash_locked_wheelhouse,
            release.reproducible_build_verified,
            release.wheel_image_surface_equal,
        )
    ):
        blockers.append(QualificationBlocker.RELEASE_BUILD_NOT_HERMETIC)
    if not release.github_actions_refs or not release.docker_base_image_digest:
        blockers.append(QualificationBlocker.SUPPLY_CHAIN_NOT_PINNED)
    if not all(
        (
            release.qualification_manifest.size_bytes > 0,
            release.sbom.size_bytes > 0,
            release.provenance.size_bytes > 0,
            release.artifact_signature.size_bytes > 0,
        )
    ):
        blockers.append(QualificationBlocker.ARTIFACT_ATTESTATION_INCOMPLETE)

    sandbox = evidence.sandbox
    if not all(
        (
            sandbox.non_root_runtime,
            sandbox.read_only_root_filesystem,
            sandbox.apparmor_loaded_and_hash_verified,
            sandbox.seccomp_loaded_and_hash_verified,
            sandbox.denied_write_capability_and_egress_tests_passed,
            sandbox.egress_destination_port_dns_allowlist_enforced,
        )
    ):
        blockers.append(QualificationBlocker.SANDBOX_NOT_ENFORCED)
    if not all(
        (
            sandbox.secrets_from_files_or_manager_only,
            sandbox.plaintext_secret_placeholders_absent,
            sandbox.secret_rotation_drill_passed,
            sandbox.operator_plane_authenticated,
            sandbox.operator_rbac_enforced,
            sandbox.audit_log_durable,
            sandbox.pause_drain_kill_switch_tested,
            sandbox.break_glass_procedure_tested,
        )
    ):
        blockers.append(QualificationBlocker.SECRET_OR_OPERATOR_POLICY_INCOMPLETE)

    if soak.duration_hours < 72:
        blockers.append(QualificationBlocker.SOAK_TOO_SHORT)
    if not (
        soak.non_synthetic_streaming_data
        and soak.real_provider_data_plane
        and soak.synthetic_contamination_count == 0
    ):
        blockers.append(
            QualificationBlocker.SOAK_SYNTHETIC_OR_NOT_RELEASE_BOUND
        )
    if set(REQUIRED_CHAOS_SCENARIOS) - set(
        soak.required_chaos_scenarios_completed
    ):
        blockers.append(QualificationBlocker.CHAOS_MATRIX_INCOMPLETE)
    if not all(
        (
            soak.provider_availability_slo_met,
            soak.rooted_freshness_slo_met,
            soak.latency_slo_met,
            soak.queue_and_cycle_slo_met,
            soak.reconciliation_slo_met,
            soak.resource_profiles_materialized,
            soak.alert_routing_and_runbooks_drilled,
            soak.accepted_cycles_have_complete_causal_economic_chain,
            soak.lost_intents == 0,
            soak.duplicate_intents == 0,
            soak.unexplained_terminal_states == 0,
        )
    ):
        blockers.append(
            QualificationBlocker.SLO_OR_TERMINAL_INVARIANTS_FAILED
        )
    if not (
        soak.evidence_signed_and_immutable and soak.independently_reviewed
    ):
        blockers.append(
            QualificationBlocker.PROMOTION_EVIDENCE_NOT_INDEPENDENT
        )

    if (
        evidence.live_execution_reachable
        or evidence.signer_reachable
        or evidence.sender_reachable
    ):
        blockers.append(
            QualificationBlocker.LIVE_OR_SIGNER_SURFACE_REACHABLE
        )

    blocker_values = tuple(sorted({item.value for item in blockers}))
    ready = not blocker_values
    return ProductionPaperQualificationReport(
        schema_version=SCHEMA_VERSION,
        ready=ready,
        blockers=blocker_values,
        evidence_hash=_stable_hash(evidence_to_dict(evidence)),
        paper_ready_allowed=ready and PAPER_READY_ALLOWED,
    )


def evidence_to_dict(
    evidence: ProductionPaperQualificationEvidence,
) -> dict[str, object]:
    """Return a deterministic JSON-compatible evidence representation."""

    return {
        "mega_pr_01_accepted": evidence.mega_pr_01_accepted,
        "mega_pr_01_report_sha256": evidence.mega_pr_01_report_sha256,
        "protocols": [
            {
                "protocol_id": item.protocol_id,
                "contract_generation": item.contract_generation,
                "credentialed_probe": _artifact_dict(item.credentialed_probe),
                "golden_fixtures": _artifact_dict(item.golden_fixtures),
                "negative_fixtures": _artifact_dict(item.negative_fixtures),
                "schema_pinned": item.schema_pinned,
                "program_and_account_identity_verified": (
                    item.program_and_account_identity_verified
                ),
                "drift_detection_materialized": item.drift_detection_materialized,
                "supported_combinations_nonempty": (
                    item.supported_combinations_nonempty
                ),
            }
            for item in evidence.protocols
        ],
        "optional_provider_ids": list(evidence.optional_provider_ids),
        "optional_providers_admitted": list(
            evidence.optional_providers_admitted
        ),
        "jupiter_contract_generations": list(
            evidence.jupiter_contract_generations
        ),
        "exact_message": {
            "compiled_message_sha256": evidence.exact_message.compiled_message_sha256,
            "simulated_message_sha256": evidence.exact_message.simulated_message_sha256,
            "transaction_proof": _artifact_dict(
                evidence.exact_message.transaction_proof
            ),
            "simulation_result": _artifact_dict(
                evidence.exact_message.simulation_result
            ),
            "economics_result": _artifact_dict(
                evidence.exact_message.economics_result
            ),
            "instruction_order_verified": (
                evidence.exact_message.instruction_order_verified
            ),
            "program_allowlist_verified": (
                evidence.exact_message.program_allowlist_verified
            ),
            "account_metas_verified": evidence.exact_message.account_metas_verified,
            "signer_writable_flags_verified": (
                evidence.exact_message.signer_writable_flags_verified
            ),
            "compute_budget_verified": (
                evidence.exact_message.compute_budget_verified
            ),
            "blockhash_validity_verified": (
                evidence.exact_message.blockhash_validity_verified
            ),
            "mutation_after_simulation_impossible": (
                evidence.exact_message.mutation_after_simulation_impossible
            ),
            "total_fees_rent_and_tips_reserved": (
                evidence.exact_message.total_fees_rent_and_tips_reserved
            ),
            "slippage_bound_verified": (
                evidence.exact_message.slippage_bound_verified
            ),
            "flash_repayment_verified": (
                evidence.exact_message.flash_repayment_verified
            ),
            "minimum_profit_verified": (
                evidence.exact_message.minimum_profit_verified
            ),
        },
        "release": {
            "source_commit": evidence.release.source_commit,
            "source_tree_sha256": evidence.release.source_tree_sha256,
            "wheel_sha256": evidence.release.wheel_sha256,
            "image_sha256": evidence.release.image_sha256,
            "config_sha256": evidence.release.config_sha256,
            "provider_contracts_sha256": (
                evidence.release.provider_contracts_sha256
            ),
            "qualification_manifest": _artifact_dict(
                evidence.release.qualification_manifest
            ),
            "sbom": _artifact_dict(evidence.release.sbom),
            "provenance": _artifact_dict(evidence.release.provenance),
            "artifact_signature": _artifact_dict(
                evidence.release.artifact_signature
            ),
            "clean_source_tree": evidence.release.clean_source_tree,
            "network_disabled_build": evidence.release.network_disabled_build,
            "offline_hash_locked_wheelhouse": (
                evidence.release.offline_hash_locked_wheelhouse
            ),
            "reproducible_build_verified": (
                evidence.release.reproducible_build_verified
            ),
            "github_actions_refs": list(evidence.release.github_actions_refs),
            "docker_base_image_digest": (
                evidence.release.docker_base_image_digest
            ),
            "wheel_image_surface_equal": (
                evidence.release.wheel_image_surface_equal
            ),
        },
        "sandbox": {
            "runtime_test_report": _artifact_dict(
                evidence.sandbox.runtime_test_report
            ),
            "apparmor_profile": _artifact_dict(
                evidence.sandbox.apparmor_profile
            ),
            "seccomp_profile": _artifact_dict(evidence.sandbox.seccomp_profile),
            "egress_policy": _artifact_dict(evidence.sandbox.egress_policy),
            "non_root_runtime": evidence.sandbox.non_root_runtime,
            "read_only_root_filesystem": (
                evidence.sandbox.read_only_root_filesystem
            ),
            "apparmor_loaded_and_hash_verified": (
                evidence.sandbox.apparmor_loaded_and_hash_verified
            ),
            "seccomp_loaded_and_hash_verified": (
                evidence.sandbox.seccomp_loaded_and_hash_verified
            ),
            "denied_write_capability_and_egress_tests_passed": (
                evidence.sandbox.denied_write_capability_and_egress_tests_passed
            ),
            "egress_destination_port_dns_allowlist_enforced": (
                evidence.sandbox.egress_destination_port_dns_allowlist_enforced
            ),
            "secrets_from_files_or_manager_only": (
                evidence.sandbox.secrets_from_files_or_manager_only
            ),
            "plaintext_secret_placeholders_absent": (
                evidence.sandbox.plaintext_secret_placeholders_absent
            ),
            "secret_rotation_drill_passed": (
                evidence.sandbox.secret_rotation_drill_passed
            ),
            "operator_plane_authenticated": (
                evidence.sandbox.operator_plane_authenticated
            ),
            "operator_rbac_enforced": evidence.sandbox.operator_rbac_enforced,
            "audit_log_durable": evidence.sandbox.audit_log_durable,
            "pause_drain_kill_switch_tested": (
                evidence.sandbox.pause_drain_kill_switch_tested
            ),
            "break_glass_procedure_tested": (
                evidence.sandbox.break_glass_procedure_tested
            ),
        },
        "soak": {
            "soak_report": _artifact_dict(evidence.soak.soak_report),
            "slo_report": _artifact_dict(evidence.soak.slo_report),
            "chaos_report": _artifact_dict(evidence.soak.chaos_report),
            "operator_drill_report": _artifact_dict(
                evidence.soak.operator_drill_report
            ),
            "independent_review": _artifact_dict(
                evidence.soak.independent_review
            ),
            "duration_hours": evidence.soak.duration_hours,
            "release_wheel_sha256": evidence.soak.release_wheel_sha256,
            "release_image_sha256": evidence.soak.release_image_sha256,
            "release_config_sha256": evidence.soak.release_config_sha256,
            "release_provider_contracts_sha256": (
                evidence.soak.release_provider_contracts_sha256
            ),
            "non_synthetic_streaming_data": (
                evidence.soak.non_synthetic_streaming_data
            ),
            "real_provider_data_plane": evidence.soak.real_provider_data_plane,
            "synthetic_contamination_count": (
                evidence.soak.synthetic_contamination_count
            ),
            "lost_intents": evidence.soak.lost_intents,
            "duplicate_intents": evidence.soak.duplicate_intents,
            "unexplained_terminal_states": (
                evidence.soak.unexplained_terminal_states
            ),
            "accepted_cycles_have_complete_causal_economic_chain": (
                evidence.soak.accepted_cycles_have_complete_causal_economic_chain
            ),
            "required_chaos_scenarios_completed": list(
                evidence.soak.required_chaos_scenarios_completed
            ),
            "provider_availability_slo_met": (
                evidence.soak.provider_availability_slo_met
            ),
            "rooted_freshness_slo_met": (
                evidence.soak.rooted_freshness_slo_met
            ),
            "latency_slo_met": evidence.soak.latency_slo_met,
            "queue_and_cycle_slo_met": (
                evidence.soak.queue_and_cycle_slo_met
            ),
            "reconciliation_slo_met": evidence.soak.reconciliation_slo_met,
            "resource_profiles_materialized": (
                evidence.soak.resource_profiles_materialized
            ),
            "alert_routing_and_runbooks_drilled": (
                evidence.soak.alert_routing_and_runbooks_drilled
            ),
            "evidence_signed_and_immutable": (
                evidence.soak.evidence_signed_and_immutable
            ),
            "independently_reviewed": evidence.soak.independently_reviewed,
        },
        "live_execution_reachable": evidence.live_execution_reachable,
        "signer_reachable": evidence.signer_reachable,
        "sender_reachable": evidence.sender_reachable,
    }


def _artifact_dict(value: MaterializedArtifact) -> dict[str, object]:
    return {
        "path": value.path,
        "sha256": value.sha256,
        "size_bytes": value.size_bytes,
        "producer_id": value.producer_id,
        "media_type": value.media_type,
    }


def _stable_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha256(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise QualificationEvidenceError(
            f"{name} must be a lowercase sha256 hex digest"
        )
    if value in {"0" * 64, "f" * 64}:
        raise QualificationEvidenceError(f"{name} must not be a placeholder digest")


def _identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise QualificationEvidenceError(f"{name} must be a stable identifier")


def _relative_path(value: str, name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or "\\" in value
        or ".." in value.split("/")
    ):
        raise QualificationEvidenceError(
            f"{name} must be a normalized relative path"
        )


def _positive_int(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise QualificationEvidenceError(f"{name} must be a positive integer")


def _non_negative_int(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise QualificationEvidenceError(
            f"{name} must be a non-negative integer"
        )
