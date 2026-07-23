"""MEGA-PR-02 protocol conformance and hermetic release qualification gate.

Side-effect-free acceptance boundary for MEGA-PR-02. The evaluator does not
import provider SDKs, open network connections, read secrets, build artifacts,
start containers, sign transactions, submit payloads or touch live funds.

A passing report means only that sender-free operational paper readiness is
qualified by protocol conformance, immutable message proof, hermetic artifacts,
sandbox evidence, release-bound soak, integer-only economics and bounded provider
HTTP behavior. Live, signer and sender remain physically disabled.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "mega-pr02.protocol-conformance-hermetic-release.v2"

REQUIRED_IMPL_FINDINGS: tuple[str, ...] = tuple(
    [f"IMPL-{i:02d}" for i in range(10, 23)] + ["IMPL-40", "IMPL-41"]
)

REQUIRED_PROTOCOLS: tuple[str, ...] = (
    "solana_v0_rpc",
    "jupiter_swap_v2_build",
    "marginfi",
    "kamino",
    "helius_webhook",
)

REQUIRED_SECURITY_SCANNERS: tuple[str, ...] = (
    "secret_scanner",
    "dependency_scanner",
    "static_security_scanner",
    "container_scanner",
    "license_scanner",
)

REQUIRED_SANDBOX_NEGATIVE_TESTS: tuple[str, ...] = (
    "read_only_root_write_denied",
    "capability_escalation_denied",
    "secret_path_unreadable_by_workload",
    "unexpected_egress_denied",
    "dns_escape_denied",
    "seccomp_profile_blocks_forbidden_syscall",
)

REQUIRED_MONETARY_FUZZ_CASES: tuple[str, ...] = (
    "float_rejected",
    "rounding_boundary_rejected",
    "negative_fee_rejected",
    "duplicate_profit_truth_rejected",
    "repayment_default_rejected",
)

REQUIRED_PROVIDER_FAILURE_CASES: tuple[str, ...] = (
    "oversized_response",
    "malformed_json",
    "wrong_content_type",
    "schema_violation",
    "slow_response_deadline",
    "retry_after_backoff",
    "non_idempotent_no_retry",
)

HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")
ACTION_PIN_RE = re.compile(r"^[0-9a-f]{40}$")


class MegaPR02GateState(str, Enum):
    """MEGA-PR-02 qualification state."""

    PRODUCTION_PAPER_QUALIFIED = "production_paper_qualified"
    BLOCKED = "blocked"


class ProtocolDisposition(str, Enum):
    """Disposition of an external protocol contract."""

    ADMITTED = "admitted"
    QUARANTINED = "quarantined"
    DISABLED = "disabled"


@dataclass(frozen=True)
class ProtocolContractEvidence:
    """Current, reviewed, credentialed external protocol contract evidence."""

    protocol: str
    disposition: ProtocolDisposition
    reviewed_contract_hash: str
    contract_reviewed_at_unix: int
    contract_expires_at_unix: int
    credentialed_probe_passed: bool
    golden_fixture_hash: str
    negative_fixture_hash: str
    schema_hash: str
    endpoint_or_program_identity_hash: str


@dataclass(frozen=True)
class ProtocolConformanceEvidence:
    """All protocol truth needed for sender-free paper qualification."""

    protocols: tuple[ProtocolContractEvidence, ...]
    optional_aggregators_disabled_or_admitted: bool
    jupiter_v1_removed_or_quarantined: bool
    jupiter_v2_build_is_canonical: bool
    helius_enqueue_before_ack_proven: bool
    helius_replay_dedup_and_gap_repair_proven: bool
    solana_finalized_v0_read_proven: bool
    marginfi_fee_truth_bound_to_deployment: bool
    kamino_fee_truth_bound_to_registry_or_chain: bool


@dataclass(frozen=True)
class MessageSimulationEvidence:
    """Exact compiled-message and simulation identity evidence."""

    compiled_v0_message_hash: str
    simulation_input_message_hash: str
    paper_acceptance_message_hash: str
    instruction_firewall_hash: str
    exact_simulation_passed: bool
    message_hash_immutable_through_acceptance: bool
    protocol_fee_rent_slippage_tip_retry_economics_complete: bool
    no_message_mutation_after_simulation: bool
    negative_instruction_fixture_hash: str


@dataclass(frozen=True)
class HermeticReleaseEvidence:
    """Release artifact and CI hermeticity evidence."""

    clean_source_export_hash: str
    clean_tree_verified: bool
    generated_artifacts_excluded: bool
    top_level_build_shadowing_prevented: bool
    isolated_verifier_environment: bool
    wheelhouse_lock_hash: str
    wheelhouse_requires_hashes: bool
    offline_network_disabled_build: bool
    dependency_attestations_verified: bool
    sbom_hash: str
    provenance_hash: str
    release_signature_hash: str
    image_digest_pinned: bool
    full_sha_actions_pinned_count: int
    workflow_actions_total: int
    mutable_workflow_actions_found: int


@dataclass(frozen=True)
class SecurityQualityEvidence:
    """Mandatory clean-release security and optimized-mode gate evidence."""

    scanners: tuple[str, ...]
    scanners_mandatory: bool
    path_aware_findings: bool
    category_aware_findings: bool
    secrets_baseline_reviewed: bool
    precommit_dependencies_pinned: bool
    lint_type_coverage_complete: bool
    optimized_mode_tests_passed: bool
    runtime_asserts_removed_from_safety_path: bool


@dataclass(frozen=True)
class SandboxReadinessEvidence:
    """Runtime-proven sandbox and service-admission evidence."""

    negative_runtime_tests: tuple[str, ...]
    apparmor_profile_loaded: bool
    seccomp_profile_loaded: bool
    egress_enforcement_runtime_proven: bool
    secret_isolation_runtime_proven: bool
    readiness_endpoint_used_for_admission: bool
    readiness_covers_worker_provider_db_queue_recovery: bool
    degraded_dependency_closes_readiness: bool


@dataclass(frozen=True)
class SoakQualificationEvidence:
    """Release-bound non-synthetic paper soak evidence."""

    soak_hours: int
    release_bound_source_hash: str
    release_bound_wheel_hash: str
    release_bound_image_hash: str
    release_bound_config_hash: str
    contract_digest_set_hash: str
    non_synthetic: bool
    no_unexplained_terminal_state: bool
    no_duplicate_intent: bool
    no_synthetic_contamination: bool
    slo_baseline_hash: str
    chaos_dr_secret_rotation_drills_hash: str
    independent_review_hash: str


@dataclass(frozen=True)
class EconomicsTruthEvidence:
    """Integer-only monetary model and single economic truth for IMPL-40."""

    immutable_economics_object_hash: str
    opportunity_profit_lamports: int
    admission_profit_lamports: int
    terminal_profit_lamports: int
    integer_denominated_only: bool
    float_inputs_rejected: bool
    metadata_profit_truth_absent: bool
    expected_profit_bound_to_economics_object: bool
    min_out_bound_to_economics_object: bool
    repayment_bound_to_protocol_evidence: bool
    protocol_fee_bound_to_protocol_evidence: bool
    silent_principal_default_forbidden: bool
    monetary_fuzz_cases: tuple[str, ...]


@dataclass(frozen=True)
class ProviderHttpTransportEvidence:
    """Canonical bounded provider HTTP runtime evidence for IMPL-41."""

    canonical_transport_hash: str
    host_allowlist_hash: str
    retry_policy_hash: str
    all_provider_clients_use_canonical_transport: bool
    streamed_response_size_limit_bytes: int
    content_type_limits_enforced: bool
    schema_limits_enforced_before_business_logic: bool
    method_aware_idempotent_retry_policy: bool
    retry_after_and_jitter_proven: bool
    non_idempotent_requests_not_retried: bool
    deadline_budget_enforced: bool
    oversized_response_fails_closed_before_decode: bool
    malformed_response_fails_closed: bool
    slow_response_fails_closed: bool
    no_oom_or_duplicate_side_effects: bool
    provider_failure_cases: tuple[str, ...]


@dataclass(frozen=True)
class MegaPR02Evidence:
    """Complete MEGA-PR-02 evidence bundle."""

    mega_pr01_accepted: bool
    mega_pr01_evidence_hash: str
    findings_covered: tuple[str, ...]
    protocol_conformance: ProtocolConformanceEvidence
    message_simulation: MessageSimulationEvidence
    hermetic_release: HermeticReleaseEvidence
    security_quality: SecurityQualityEvidence
    sandbox_readiness: SandboxReadinessEvidence
    soak_qualification: SoakQualificationEvidence
    economics_truth: EconomicsTruthEvidence
    provider_http_transport: ProviderHttpTransportEvidence
    live_execution_requested: bool = False
    signer_requested: bool = False
    sender_requested: bool = False
    private_key_material_present: bool = False


@dataclass(frozen=True)
class MegaPR02Violation:
    code: str
    message: str


@dataclass(frozen=True)
class MegaPR02Report:
    schema_version: str
    state: MegaPR02GateState
    blockers: tuple[MegaPR02Violation, ...]
    evidence_hash: str
    covered_findings: tuple[str, ...]
    transaction_signer_allowed: bool
    sender_allowed: bool
    live_execution_allowed: bool
    private_key_material_allowed: bool


def evaluate_mega_pr02_evidence(evidence: MegaPR02Evidence) -> MegaPR02Report:
    """Validate a MEGA-PR-02 evidence bundle without side effects."""

    blockers: list[MegaPR02Violation] = []
    _validate_no_runtime_enablement(evidence, blockers)
    _validate_mega_pr01_dependency(evidence, blockers)
    _validate_findings(evidence.findings_covered, blockers)
    _validate_protocol_conformance(evidence.protocol_conformance, blockers)
    _validate_message_simulation(evidence.message_simulation, blockers)
    _validate_hermetic_release(evidence.hermetic_release, blockers)
    _validate_security_quality(evidence.security_quality, blockers)
    _validate_sandbox(evidence.sandbox_readiness, blockers)
    _validate_soak(evidence.soak_qualification, blockers)
    _validate_economics_truth(evidence.economics_truth, blockers)
    _validate_provider_http_transport(evidence.provider_http_transport, blockers)

    unique = tuple(_dedupe(blockers))
    state = (
        MegaPR02GateState.BLOCKED
        if unique
        else MegaPR02GateState.PRODUCTION_PAPER_QUALIFIED
    )
    return MegaPR02Report(
        schema_version=SCHEMA_VERSION,
        state=state,
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        covered_findings=tuple(sorted(set(evidence.findings_covered))),
        transaction_signer_allowed=False,
        sender_allowed=False,
        live_execution_allowed=False,
        private_key_material_allowed=False,
    )


def blockers_by_code(report: MegaPR02Report) -> Mapping[str, MegaPR02Violation]:
    """Return blockers keyed by code for compact assertions and reporting."""

    return {blocker.code: blocker for blocker in report.blockers}


def _validate_no_runtime_enablement(
    evidence: MegaPR02Evidence,
    blockers: list[MegaPR02Violation],
) -> None:
    if evidence.live_execution_requested:
        _add(blockers, "MEGA_PR02_LIVE_REQUESTED", "MEGA-PR-02 cannot enable live")
    if evidence.signer_requested:
        _add(blockers, "MEGA_PR02_SIGNER_REQUESTED", "MEGA-PR-02 cannot enable signer")
    if evidence.sender_requested:
        _add(blockers, "MEGA_PR02_SENDER_REQUESTED", "MEGA-PR-02 cannot enable sender")
    if evidence.private_key_material_present:
        _add(
            blockers,
            "MEGA_PR02_PRIVATE_KEY_PRESENT",
            "private key material is forbidden in paper qualification",
        )


def _validate_mega_pr01_dependency(
    evidence: MegaPR02Evidence,
    blockers: list[MegaPR02Violation],
) -> None:
    if not evidence.mega_pr01_accepted:
        _add(
            blockers,
            "MEGA_PR02_MPR01_NOT_ACCEPTED",
            "MEGA-PR-02 requires accepted MEGA-PR-01 evidence first",
        )
    if not _is_strict_sha256(evidence.mega_pr01_evidence_hash):
        _add(
            blockers,
            "MEGA_PR02_BAD_MPR01_EVIDENCE_HASH",
            "MEGA-PR-01 evidence hash must be strict sha256",
        )


def _validate_findings(
    findings_covered: Sequence[str],
    blockers: list[MegaPR02Violation],
) -> None:
    covered = set(findings_covered)
    missing = [finding for finding in REQUIRED_IMPL_FINDINGS if finding not in covered]
    if missing:
        _add(
            blockers,
            "MEGA_PR02_FINDINGS_INCOMPLETE",
            f"missing required implementation findings: {', '.join(missing)}",
        )


def _validate_protocol_conformance(
    evidence: ProtocolConformanceEvidence,
    blockers: list[MegaPR02Violation],
) -> None:
    by_protocol = {item.protocol: item for item in evidence.protocols}
    for protocol in REQUIRED_PROTOCOLS:
        item = by_protocol.get(protocol)
        if item is None:
            _add(blockers, "MEGA_PR02_PROTOCOL_MISSING", f"{protocol} missing")
            continue
        if item.disposition != ProtocolDisposition.ADMITTED:
            _add(
                blockers,
                "MEGA_PR02_PROTOCOL_NOT_ADMITTED",
                f"{protocol} is not admitted",
            )
        if not item.credentialed_probe_passed:
            _add(
                blockers,
                "MEGA_PR02_PROTOCOL_PROBE_MISSING",
                f"{protocol} lacks credentialed/current conformance probe",
            )
        if item.contract_expires_at_unix <= item.contract_reviewed_at_unix:
            _add(
                blockers,
                "MEGA_PR02_PROTOCOL_EXPIRY_INVALID",
                f"{protocol} expiry must be after review time",
            )
        for field_name, value in (
            ("reviewed_contract_hash", item.reviewed_contract_hash),
            ("golden_fixture_hash", item.golden_fixture_hash),
            ("negative_fixture_hash", item.negative_fixture_hash),
            ("schema_hash", item.schema_hash),
            (
                "endpoint_or_program_identity_hash",
                item.endpoint_or_program_identity_hash,
            ),
        ):
            if not _is_strict_sha256(value):
                _add(
                    blockers,
                    "MEGA_PR02_PROTOCOL_BAD_HASH",
                    f"{protocol}.{field_name} is not strict sha256",
                )
    if not evidence.optional_aggregators_disabled_or_admitted:
        _add(
            blockers,
            "MEGA_PR02_OPTIONAL_AGGREGATORS_UNCONTROLLED",
            "optional aggregators must be disabled or admitted",
        )
    if not evidence.jupiter_v1_removed_or_quarantined:
        _add(
            blockers,
            "MEGA_PR02_JUPITER_V1_ACTIVE",
            "Jupiter V1 must be removed or explicitly quarantined",
        )
    if not evidence.jupiter_v2_build_is_canonical:
        _add(
            blockers,
            "MEGA_PR02_JUPITER_V2_NOT_CANONICAL",
            "Jupiter Swap V2 /build must be the admitted composition contract",
        )
    if not evidence.helius_enqueue_before_ack_proven:
        _add(
            blockers,
            "MEGA_PR02_HELIUS_ACK_UNDURABLE",
            "Helius intake must durably enqueue before ACK",
        )
    if not evidence.helius_replay_dedup_and_gap_repair_proven:
        _add(
            blockers,
            "MEGA_PR02_HELIUS_REPAIR_MISSING",
            "Helius replay/dedup/gap repair evidence is required",
        )
    if not evidence.solana_finalized_v0_read_proven:
        _add(
            blockers,
            "MEGA_PR02_SOLANA_FINALIZED_V0_MISSING",
            "Solana finalized v0 read evidence is required",
        )
    if not evidence.marginfi_fee_truth_bound_to_deployment:
        _add(
            blockers,
            "MEGA_PR02_MARGINFI_FEE_UNBOUND",
            "MarginFi fee truth must be deployment-bound",
        )
    if not evidence.kamino_fee_truth_bound_to_registry_or_chain:
        _add(
            blockers,
            "MEGA_PR02_KAMINO_FEE_UNBOUND",
            "Kamino fee truth must be registry or chain bound",
        )


def _validate_message_simulation(
    evidence: MessageSimulationEvidence,
    blockers: list[MegaPR02Violation],
) -> None:
    for field_name, value in (
        ("compiled_v0_message_hash", evidence.compiled_v0_message_hash),
        ("simulation_input_message_hash", evidence.simulation_input_message_hash),
        ("paper_acceptance_message_hash", evidence.paper_acceptance_message_hash),
        ("instruction_firewall_hash", evidence.instruction_firewall_hash),
        ("negative_instruction_fixture_hash", evidence.negative_instruction_fixture_hash),
    ):
        if not _is_strict_sha256(value):
            _add(blockers, "MEGA_PR02_MESSAGE_BAD_HASH", f"{field_name} invalid")
    if not (
        evidence.compiled_v0_message_hash
        == evidence.simulation_input_message_hash
        == evidence.paper_acceptance_message_hash
    ):
        _add(
            blockers,
            "MEGA_PR02_MESSAGE_HASH_MUTATED",
            "compiled message hash must be unchanged through simulation and paper acceptance",
        )
    if not evidence.exact_simulation_passed:
        _add(
            blockers,
            "MEGA_PR02_EXACT_SIMULATION_MISSING",
            "exact compiled message simulation is required",
        )
    if not evidence.message_hash_immutable_through_acceptance:
        _add(
            blockers,
            "MEGA_PR02_MESSAGE_IMMUTABILITY_UNPROVEN",
            "message hash immutability evidence is required",
        )
    if not evidence.protocol_fee_rent_slippage_tip_retry_economics_complete:
        _add(
            blockers,
            "MEGA_PR02_ECONOMICS_INCOMPLETE",
            "fees/rent/slippage/tip/retry economics must be complete",
        )
    if not evidence.no_message_mutation_after_simulation:
        _add(
            blockers,
            "MEGA_PR02_POST_SIMULATION_MUTATION",
            "message cannot mutate after exact simulation",
        )


def _validate_hermetic_release(
    evidence: HermeticReleaseEvidence,
    blockers: list[MegaPR02Violation],
) -> None:
    for field_name, value in (
        ("clean_source_export_hash", evidence.clean_source_export_hash),
        ("wheelhouse_lock_hash", evidence.wheelhouse_lock_hash),
        ("sbom_hash", evidence.sbom_hash),
        ("provenance_hash", evidence.provenance_hash),
        ("release_signature_hash", evidence.release_signature_hash),
    ):
        if not _is_strict_sha256(value):
            _add(blockers, "MEGA_PR02_RELEASE_BAD_HASH", f"{field_name} invalid")
    if not evidence.clean_tree_verified:
        _add(
            blockers,
            "MEGA_PR02_CLEAN_TREE_UNVERIFIED",
            "release must start from a clean VCS checkout/export",
        )
    if not evidence.generated_artifacts_excluded:
        _add(
            blockers,
            "MEGA_PR02_GENERATED_ARTIFACTS_INCLUDED",
            "generated artifacts must not contaminate release input",
        )
    if not evidence.top_level_build_shadowing_prevented:
        _add(
            blockers,
            "MEGA_PR02_BUILD_SHADOWING_PRESENT",
            "top-level build/ must not shadow python -m build",
        )
    if not evidence.isolated_verifier_environment:
        _add(
            blockers,
            "MEGA_PR02_VERIFIER_AMBIENT_ENV",
            "aggregate verifier must run in an isolated environment",
        )
    if not evidence.wheelhouse_requires_hashes:
        _add(
            blockers,
            "MEGA_PR02_WHEELHOUSE_NOT_HASH_LOCKED",
            "wheelhouse lock must require hashes",
        )
    if not evidence.offline_network_disabled_build:
        _add(
            blockers,
            "MEGA_PR02_RELEASE_BUILD_ONLINE",
            "release build must run with network disabled",
        )
    if not evidence.dependency_attestations_verified:
        _add(
            blockers,
            "MEGA_PR02_DEP_ATTESTATIONS_MISSING",
            "dependency attestations/hashes must be verified",
        )
    if not evidence.image_digest_pinned:
        _add(
            blockers,
            "MEGA_PR02_IMAGE_DIGEST_UNPINNED",
            "runtime images must be digest pinned",
        )
    if evidence.workflow_actions_total <= 0:
        _add(
            blockers,
            "MEGA_PR02_NO_WORKFLOW_ACTIONS",
            "workflow action inventory must be non-empty",
        )
    if evidence.full_sha_actions_pinned_count != evidence.workflow_actions_total:
        _add(
            blockers,
            "MEGA_PR02_ACTIONS_NOT_FULL_SHA_PINNED",
            "all workflow actions must be reviewed full-SHA pins",
        )
    if evidence.mutable_workflow_actions_found != 0:
        _add(
            blockers,
            "MEGA_PR02_MUTABLE_ACTIONS_FOUND",
            "mutable workflow action refs are forbidden",
        )


def _validate_security_quality(
    evidence: SecurityQualityEvidence,
    blockers: list[MegaPR02Violation],
) -> None:
    scanners = set(evidence.scanners)
    missing = [scanner for scanner in REQUIRED_SECURITY_SCANNERS if scanner not in scanners]
    if missing:
        _add(
            blockers,
            "MEGA_PR02_SECURITY_SCANNERS_MISSING",
            f"missing security scanners: {', '.join(missing)}",
        )
    if not evidence.scanners_mandatory:
        _add(
            blockers,
            "MEGA_PR02_SECURITY_SCANNERS_OPTIONAL",
            "security scanners must be mandatory gates",
        )
    if not evidence.path_aware_findings:
        _add(
            blockers,
            "MEGA_PR02_SECURITY_NOT_PATH_AWARE",
            "security findings must be path-aware",
        )
    if not evidence.category_aware_findings:
        _add(
            blockers,
            "MEGA_PR02_SECURITY_NOT_CATEGORY_AWARE",
            "security findings must be category-aware",
        )
    if not evidence.secrets_baseline_reviewed:
        _add(
            blockers,
            "MEGA_PR02_SECRETS_BASELINE_UNREVIEWED",
            ".secrets.baseline must be restored/reviewed",
        )
    if not evidence.precommit_dependencies_pinned:
        _add(
            blockers,
            "MEGA_PR02_PRECOMMIT_UNPINNED",
            "pre-commit dependencies must be pinned",
        )
    if not evidence.lint_type_coverage_complete:
        _add(
            blockers,
            "MEGA_PR02_LINT_TYPE_INCOMPLETE",
            "lint/type coverage must be complete",
        )
    if not evidence.optimized_mode_tests_passed:
        _add(
            blockers,
            "MEGA_PR02_OPTIMIZED_MODE_UNTESTED",
            "python -O optimized-mode suite is required",
        )
    if not evidence.runtime_asserts_removed_from_safety_path:
        _add(
            blockers,
            "MEGA_PR02_RUNTIME_ASSERTS_REMAIN",
            "safety-relevant runtime asserts must be explicit validations",
        )


def _validate_sandbox(
    evidence: SandboxReadinessEvidence,
    blockers: list[MegaPR02Violation],
) -> None:
    tests = set(evidence.negative_runtime_tests)
    missing = [case for case in REQUIRED_SANDBOX_NEGATIVE_TESTS if case not in tests]
    if missing:
        _add(
            blockers,
            "MEGA_PR02_SANDBOX_TESTS_MISSING",
            f"missing sandbox tests: {', '.join(missing)}",
        )
    if not evidence.apparmor_profile_loaded:
        _add(blockers, "MEGA_PR02_APPARMOR_MISSING", "AppArmor profile must load")
    if not evidence.seccomp_profile_loaded:
        _add(blockers, "MEGA_PR02_SECCOMP_MISSING", "seccomp profile must load")
    if not evidence.egress_enforcement_runtime_proven:
        _add(
            blockers,
            "MEGA_PR02_EGRESS_UNPROVEN",
            "egress/DNS controls must be runtime-proven",
        )
    if not evidence.secret_isolation_runtime_proven:
        _add(
            blockers,
            "MEGA_PR02_SECRET_ISOLATION_UNPROVEN",
            "secret isolation must be runtime-proven",
        )
    if not evidence.readiness_endpoint_used_for_admission:
        _add(
            blockers,
            "MEGA_PR02_READY_NOT_ADMISSION",
            "/ready must be used for service admission",
        )
    if not evidence.readiness_covers_worker_provider_db_queue_recovery:
        _add(
            blockers,
            "MEGA_PR02_READY_INCOMPLETE",
            "readiness must cover worker/provider/DB/queue/recovery",
        )
    if not evidence.degraded_dependency_closes_readiness:
        _add(
            blockers,
            "MEGA_PR02_READY_STAYS_OPEN_ON_DEGRADATION",
            "degraded critical dependencies must close readiness",
        )


def _validate_soak(
    evidence: SoakQualificationEvidence,
    blockers: list[MegaPR02Violation],
) -> None:
    for field_name, value in (
        ("release_bound_source_hash", evidence.release_bound_source_hash),
        ("release_bound_wheel_hash", evidence.release_bound_wheel_hash),
        ("release_bound_image_hash", evidence.release_bound_image_hash),
        ("release_bound_config_hash", evidence.release_bound_config_hash),
        ("contract_digest_set_hash", evidence.contract_digest_set_hash),
        ("slo_baseline_hash", evidence.slo_baseline_hash),
        (
            "chaos_dr_secret_rotation_drills_hash",
            evidence.chaos_dr_secret_rotation_drills_hash,
        ),
        ("independent_review_hash", evidence.independent_review_hash),
    ):
        if not _is_strict_sha256(value):
            _add(blockers, "MEGA_PR02_SOAK_BAD_HASH", f"{field_name} invalid")
    if evidence.soak_hours < 72:
        _add(
            blockers,
            "MEGA_PR02_SOAK_TOO_SHORT",
            "release-bound non-synthetic soak must be at least 72 hours",
        )
    if not evidence.non_synthetic:
        _add(blockers, "MEGA_PR02_SOAK_SYNTHETIC", "soak cannot be synthetic")
    if not evidence.no_unexplained_terminal_state:
        _add(
            blockers,
            "MEGA_PR02_SOAK_UNEXPLAINED_TERMINAL_STATE",
            "soak cannot contain unexplained terminal state",
        )
    if not evidence.no_duplicate_intent:
        _add(
            blockers,
            "MEGA_PR02_SOAK_DUPLICATE_INTENT",
            "soak cannot contain duplicate intent",
        )
    if not evidence.no_synthetic_contamination:
        _add(
            blockers,
            "MEGA_PR02_SOAK_SYNTHETIC_CONTAMINATION",
            "soak evidence must be free of synthetic contamination",
        )


def _validate_economics_truth(
    evidence: EconomicsTruthEvidence,
    blockers: list[MegaPR02Violation],
) -> None:
    if not _is_strict_sha256(evidence.immutable_economics_object_hash):
        _add(
            blockers,
            "MEGA_PR02_ECONOMICS_BAD_HASH",
            "immutable economics object hash must be strict sha256",
        )
    for field_name, value in (
        ("opportunity_profit_lamports", evidence.opportunity_profit_lamports),
        ("admission_profit_lamports", evidence.admission_profit_lamports),
        ("terminal_profit_lamports", evidence.terminal_profit_lamports),
    ):
        if not _is_nonnegative_int(value):
            _add(
                blockers,
                "MEGA_PR02_ECONOMICS_NON_INTEGER_AMOUNT",
                f"{field_name} must be a non-negative int",
            )
    if not (
        evidence.opportunity_profit_lamports
        == evidence.admission_profit_lamports
        == evidence.terminal_profit_lamports
    ):
        _add(
            blockers,
            "MEGA_PR02_ECONOMICS_DUPLICATE_PROFIT_TRUTH",
            "opportunity, admission and terminal profit must derive from one immutable object",
        )
    if not evidence.integer_denominated_only:
        _add(
            blockers,
            "MEGA_PR02_ECONOMICS_NOT_INTEGER_ONLY",
            "monetary model must be integer-denominated only",
        )
    if not evidence.float_inputs_rejected:
        _add(
            blockers,
            "MEGA_PR02_FLOAT_INPUTS_ACCEPTED",
            "float inputs must be rejected at every ingestion boundary",
        )
    if not evidence.metadata_profit_truth_absent:
        _add(
            blockers,
            "MEGA_PR02_METADATA_PROFIT_TRUTH_PRESENT",
            "separate metadata profit truth is forbidden",
        )
    if not evidence.expected_profit_bound_to_economics_object:
        _add(
            blockers,
            "MEGA_PR02_EXPECTED_PROFIT_UNBOUND",
            "expected profit must be bound to the economics object",
        )
    if not evidence.min_out_bound_to_economics_object:
        _add(
            blockers,
            "MEGA_PR02_MIN_OUT_UNBOUND",
            "min-out must be bound to the economics object",
        )
    if not evidence.repayment_bound_to_protocol_evidence:
        _add(
            blockers,
            "MEGA_PR02_REPAYMENT_UNBOUND",
            "repayment must be protocol-bound, not a silent principal default",
        )
    if not evidence.protocol_fee_bound_to_protocol_evidence:
        _add(
            blockers,
            "MEGA_PR02_PROTOCOL_FEE_UNBOUND",
            "protocol fee truth must be bound to protocol/deployment evidence",
        )
    if not evidence.silent_principal_default_forbidden:
        _add(
            blockers,
            "MEGA_PR02_SILENT_PRINCIPAL_DEFAULT",
            "silent principal default is forbidden",
        )
    cases = set(evidence.monetary_fuzz_cases)
    missing = [case for case in REQUIRED_MONETARY_FUZZ_CASES if case not in cases]
    if missing:
        _add(
            blockers,
            "MEGA_PR02_MONETARY_FUZZ_INCOMPLETE",
            f"missing monetary fuzz cases: {', '.join(missing)}",
        )


def _validate_provider_http_transport(
    evidence: ProviderHttpTransportEvidence,
    blockers: list[MegaPR02Violation],
) -> None:
    for field_name, value in (
        ("canonical_transport_hash", evidence.canonical_transport_hash),
        ("host_allowlist_hash", evidence.host_allowlist_hash),
        ("retry_policy_hash", evidence.retry_policy_hash),
    ):
        if not _is_strict_sha256(value):
            _add(blockers, "MEGA_PR02_TRANSPORT_BAD_HASH", f"{field_name} invalid")
    if not evidence.all_provider_clients_use_canonical_transport:
        _add(
            blockers,
            "MEGA_PR02_PROVIDER_TRANSPORT_FRAGMENTED",
            "all provider clients must use one canonical transport",
        )
    if not _is_positive_int(evidence.streamed_response_size_limit_bytes):
        _add(
            blockers,
            "MEGA_PR02_PROVIDER_RESPONSE_LIMIT_INVALID",
            "streamed response-size limit must be a positive int",
        )
    if not evidence.content_type_limits_enforced:
        _add(
            blockers,
            "MEGA_PR02_CONTENT_TYPE_UNBOUNDED",
            "content-type limits must be enforced before decode",
        )
    if not evidence.schema_limits_enforced_before_business_logic:
        _add(
            blockers,
            "MEGA_PR02_SCHEMA_LIMITS_LATE",
            "schema limits must run before business logic",
        )
    if not evidence.method_aware_idempotent_retry_policy:
        _add(
            blockers,
            "MEGA_PR02_RETRY_POLICY_NOT_METHOD_AWARE",
            "retry policy must be method and idempotency aware",
        )
    if not evidence.retry_after_and_jitter_proven:
        _add(
            blockers,
            "MEGA_PR02_RETRY_AFTER_JITTER_MISSING",
            "Retry-After and jitter behavior must be proven",
        )
    if not evidence.non_idempotent_requests_not_retried:
        _add(
            blockers,
            "MEGA_PR02_NON_IDEMPOTENT_RETRIED",
            "non-idempotent requests must not be retried",
        )
    if not evidence.deadline_budget_enforced:
        _add(
            blockers,
            "MEGA_PR02_PROVIDER_DEADLINE_UNBOUNDED",
            "provider HTTP runtime must enforce deadlines",
        )
    if not evidence.oversized_response_fails_closed_before_decode:
        _add(
            blockers,
            "MEGA_PR02_OVERSIZED_RESPONSE_NOT_FAIL_CLOSED",
            "oversized responses must fail closed before decode",
        )
    if not evidence.malformed_response_fails_closed:
        _add(
            blockers,
            "MEGA_PR02_MALFORMED_RESPONSE_NOT_FAIL_CLOSED",
            "malformed responses must fail closed",
        )
    if not evidence.slow_response_fails_closed:
        _add(
            blockers,
            "MEGA_PR02_SLOW_RESPONSE_NOT_FAIL_CLOSED",
            "slow responses must fail closed",
        )
    if not evidence.no_oom_or_duplicate_side_effects:
        _add(
            blockers,
            "MEGA_PR02_PROVIDER_SIDE_EFFECT_RISK",
            "provider failures cannot cause OOM or duplicate side effects",
        )
    cases = set(evidence.provider_failure_cases)
    missing = [case for case in REQUIRED_PROVIDER_FAILURE_CASES if case not in cases]
    if missing:
        _add(
            blockers,
            "MEGA_PR02_PROVIDER_FAILURE_CASES_INCOMPLETE",
            f"missing provider failure cases: {', '.join(missing)}",
        )


def _stable_hash(value: object) -> str:
    payload = json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _jsonable(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(v) for v in value]
    return value


def _is_strict_sha256(value: str) -> bool:
    return isinstance(value, str) and bool(HEX_64_RE.fullmatch(value))


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _add(blockers: list[MegaPR02Violation], code: str, message: str) -> None:
    blockers.append(MegaPR02Violation(code=code, message=message))


def _dedupe(blockers: Iterable[MegaPR02Violation]) -> tuple[MegaPR02Violation, ...]:
    seen: set[str] = set()
    unique: list[MegaPR02Violation] = []
    for blocker in blockers:
        key = f"{blocker.code}:{blocker.message}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(blocker)
    return tuple(unique)
