"""MEGA-PR-02 protocol conformance and hermetic release qualification gate.

This module is intentionally side-effect free. It does not import provider SDKs,
open network connections, read secrets, build artifacts, start containers, sign
transactions, or submit payloads. It defines the deterministic evidence contract
that must be satisfied before the repository can claim production-qualified
sender-free paper readiness.

MEGA-PR-02 keeps live execution physically disabled. A passing report only means
that the paper system has release-bound protocol conformance, immutable message
proof, hermetic artifacts, hardened sandbox evidence and a non-synthetic soak.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "mega-pr02.protocol-conformance-hermetic-release.v1"

REQUIRED_IMPL_FINDINGS: tuple[str, ...] = tuple(f"IMPL-{i:02d}" for i in range(10, 23))

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
    stale_docs_admitted: bool = False
    arbitrary_env_truth_admitted: bool = False
    unverified_constant_admitted: bool = False


@dataclass(frozen=True)
class ProtocolConformanceEvidence:
    """Protocol-level truth required for paper critical path admission."""

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
    """Exact transaction proof for sender-free paper acceptance."""

    compiled_v0_message_hash: str
    simulation_input_message_hash: str
    paper_acceptance_message_hash: str
    instruction_firewall_manifest_hash: str
    exact_simulation_report_hash: str
    protocol_economics_report_hash: str
    fees_rent_slippage_tip_retry_complete: bool
    mutation_after_simulation_detected: bool
    protocol_fee_sources_chain_or_contract_bound: bool
    paper_outcome_bound_to_message_hash: bool


@dataclass(frozen=True)
class HermeticReleaseEvidence:
    """Clean-tree, offline and reproducible release evidence."""

    source_export_manifest_hash: str
    clean_tree_verified: bool
    generated_artifacts_excluded: bool
    top_level_build_shadowing_prevented: bool
    aggregate_verifier_uses_isolated_environment: bool
    hash_locked_wheelhouse_manifest_hash: str
    offline_build_network_disabled: bool
    package_attestations_verified: bool
    sbom_hash: str
    provenance_hash: str
    release_signature_hash: str
    docker_base_image_pinned_by_digest: bool
    github_actions_total_uses: int
    github_actions_full_sha_pins: int
    mutable_action_refs: tuple[str, ...]


@dataclass(frozen=True)
class SecurityQualityEvidence:
    """Mandatory path-aware security and optimized-mode quality gate."""

    mandatory_scanners: tuple[str, ...]
    scanner_policy_hash: str
    path_aware_findings: bool
    category_aware_findings: bool
    secrets_baseline_reviewed_or_removed: bool
    pre_commit_dependencies_pinned: bool
    security_gate_runs_in_clean_aggregate: bool
    runtime_asserts_replaced_on_critical_path: bool
    optimized_mode_tests_passed: bool
    lint_type_coverage_hash: str
    no_python_o_validation_loss: bool


@dataclass(frozen=True)
class SandboxReadinessEvidence:
    """Runtime-proven sandbox and readiness evidence."""

    apparmor_profile_hash: str
    seccomp_profile_hash: str
    egress_policy_hash: str
    apparmor_loaded: bool
    seccomp_loaded: bool
    destination_port_dns_egress_enforced: bool
    secret_isolation_proven: bool
    negative_runtime_tests: tuple[str, ...]
    health_is_liveness_only: bool
    readiness_endpoint_configured_for_admission: bool
    readiness_checks_worker_provider_db_queue_recovery: bool
    readiness_false_on_critical_degradation: bool


@dataclass(frozen=True)
class SoakQualificationEvidence:
    """Release-bound non-synthetic production paper soak evidence."""

    duration_hours: float
    non_synthetic: bool
    source_commit_hash: str
    wheel_hash: str
    image_digest_hash: str
    config_digest_hash: str
    contract_digest_hash: str
    evidence_bundle_hash: str
    slo_baseline_hash: str
    chaos_dr_secret_rotation_report_hash: str
    no_unexplained_terminal_state: bool
    no_duplicate_intent: bool
    no_synthetic_contamination: bool
    independent_review_signed: bool
    product_state_changes_to_paper_ready_only: bool


@dataclass(frozen=True)
class MegaPR02Evidence:
    """Top-level MEGA-PR-02 evidence envelope."""

    mega_pr01_accepted: bool
    mega_pr01_evidence_hash: str
    findings_covered: tuple[str, ...]
    protocol_conformance: ProtocolConformanceEvidence
    message_simulation: MessageSimulationEvidence
    hermetic_release: HermeticReleaseEvidence
    security_quality: SecurityQualityEvidence
    sandbox_readiness: SandboxReadinessEvidence
    soak: SoakQualificationEvidence
    signer_present: bool = False
    sender_present: bool = False
    live_execution_present: bool = False
    private_key_material_present: bool = False


@dataclass(frozen=True)
class MegaPR02Violation:
    """A deterministic blocker for MEGA-PR-02 qualification."""

    code: str
    message: str


@dataclass(frozen=True)
class MegaPR02Report:
    """MEGA-PR-02 deterministic gate report."""

    schema_version: str
    state: MegaPR02GateState
    blockers: tuple[MegaPR02Violation, ...]
    evidence_hash: str
    covered_findings: tuple[str, ...]
    paper_ready_allowed: bool
    transaction_signer_allowed: bool
    sender_allowed: bool
    live_execution_allowed: bool


def evaluate_mega_pr02_evidence(evidence: MegaPR02Evidence) -> MegaPR02Report:
    """Evaluate MEGA-PR-02 acceptance evidence without side effects."""

    blockers: list[MegaPR02Violation] = []
    _validate_no_live_surface(evidence, blockers)
    _validate_dependency_boundary(evidence, blockers)
    _validate_findings(evidence.findings_covered, blockers)
    _validate_protocol_conformance(evidence.protocol_conformance, blockers)
    _validate_message_simulation(evidence.message_simulation, blockers)
    _validate_hermetic_release(evidence.hermetic_release, blockers)
    _validate_security_quality(evidence.security_quality, blockers)
    _validate_sandbox_readiness(evidence.sandbox_readiness, blockers)
    _validate_soak(evidence.soak, blockers)

    unique_blockers = tuple(_dedupe(blockers))
    state = (
        MegaPR02GateState.BLOCKED
        if unique_blockers
        else MegaPR02GateState.PRODUCTION_PAPER_QUALIFIED
    )
    return MegaPR02Report(
        schema_version=SCHEMA_VERSION,
        state=state,
        blockers=unique_blockers,
        evidence_hash=_stable_hash(evidence),
        covered_findings=tuple(sorted(set(evidence.findings_covered))),
        paper_ready_allowed=not unique_blockers,
        transaction_signer_allowed=False,
        sender_allowed=False,
        live_execution_allowed=False,
    )


def _validate_no_live_surface(
    evidence: MegaPR02Evidence,
    blockers: list[MegaPR02Violation],
) -> None:
    if evidence.signer_present:
        _add(blockers, "MEGA_PR02_SIGNER_PRESENT", "MEGA-PR-02 must not ship signer access")
    if evidence.sender_present:
        _add(blockers, "MEGA_PR02_SENDER_PRESENT", "MEGA-PR-02 must not ship sender submission")
    if evidence.live_execution_present:
        _add(blockers, "MEGA_PR02_LIVE_PRESENT", "MEGA-PR-02 must not enable live execution")
    if evidence.private_key_material_present:
        _add(blockers, "MEGA_PR02_PRIVATE_KEY_PRESENT", "private key material is forbidden")


def _validate_dependency_boundary(
    evidence: MegaPR02Evidence,
    blockers: list[MegaPR02Violation],
) -> None:
    if not evidence.mega_pr01_accepted:
        _add(
            blockers,
            "MEGA_PR02_MISSING_MEGA_PR01",
            "MEGA-PR-02 depends on accepted MEGA-PR-01 paper vertical",
        )
    if not _is_sha256(evidence.mega_pr01_evidence_hash):
        _add(
            blockers,
            "MEGA_PR02_BAD_MEGA_PR01_HASH",
            "MEGA-PR-01 evidence hash must be strict sha256",
        )


def _validate_findings(
    findings: Sequence[str],
    blockers: list[MegaPR02Violation],
) -> None:
    missing = [finding for finding in REQUIRED_IMPL_FINDINGS if finding not in set(findings)]
    if missing:
        _add(
            blockers,
            "MEGA_PR02_FINDINGS_INCOMPLETE",
            f"missing V2 implementation findings: {', '.join(missing)}",
        )


def _validate_protocol_conformance(
    evidence: ProtocolConformanceEvidence,
    blockers: list[MegaPR02Violation],
) -> None:
    by_name: dict[str, ProtocolContractEvidence] = {}
    for contract in evidence.protocols:
        if contract.protocol in by_name:
            _add(blockers, "MEGA_PR02_DUPLICATE_PROTOCOL", f"duplicate protocol {contract.protocol}")
        by_name[contract.protocol] = contract
        _validate_protocol_contract(contract, blockers)

    for protocol in REQUIRED_PROTOCOLS:
        contract = by_name.get(protocol)
        if contract is None:
            _add(blockers, "MEGA_PR02_PROTOCOL_MISSING", f"{protocol} evidence is required")
        elif contract.disposition != ProtocolDisposition.ADMITTED:
            _add(blockers, "MEGA_PR02_PROTOCOL_NOT_ADMITTED", f"{protocol} must be admitted")

    if not evidence.optional_aggregators_disabled_or_admitted:
        _add(
            blockers,
            "MEGA_PR02_OPTIONAL_AGGREGATORS_AMBIGUOUS",
            "optional aggregators must be disabled or fully admitted",
        )
    if not evidence.jupiter_v1_removed_or_quarantined:
        _add(blockers, "MEGA_PR02_JUPITER_V1_ACTIVE", "Jupiter V1 must be removed or quarantined")
    if not evidence.jupiter_v2_build_is_canonical:
        _add(blockers, "MEGA_PR02_JUPITER_V2_NOT_CANONICAL", "Jupiter V2 /build must be canonical")
    if not evidence.helius_enqueue_before_ack_proven:
        _add(blockers, "MEGA_PR02_HELIUS_ACK_UNSAFE", "Helius must enqueue durably before ACK")
    if not evidence.helius_replay_dedup_and_gap_repair_proven:
        _add(blockers, "MEGA_PR02_HELIUS_REPAIR_MISSING", "Helius replay/dedup/gap repair is required")
    if not evidence.solana_finalized_v0_read_proven:
        _add(blockers, "MEGA_PR02_SOLANA_V0_FINALITY_MISSING", "Solana v0 finalized read proof is required")
    if not evidence.marginfi_fee_truth_bound_to_deployment:
        _add(blockers, "MEGA_PR02_MARGINFI_FEE_UNBOUND", "MarginFi fee truth must be deployment bound")
    if not evidence.kamino_fee_truth_bound_to_registry_or_chain:
        _add(blockers, "MEGA_PR02_KAMINO_FEE_UNBOUND", "Kamino fee truth must be registry/chain bound")


def _validate_protocol_contract(
    contract: ProtocolContractEvidence,
    blockers: list[MegaPR02Violation],
) -> None:
    if not contract.protocol:
        _add(blockers, "MEGA_PR02_EMPTY_PROTOCOL", "protocol name is required")
    for field_name, value in (
        ("reviewed_contract_hash", contract.reviewed_contract_hash),
        ("golden_fixture_hash", contract.golden_fixture_hash),
        ("negative_fixture_hash", contract.negative_fixture_hash),
        ("schema_hash", contract.schema_hash),
        ("endpoint_or_program_identity_hash", contract.endpoint_or_program_identity_hash),
    ):
        if not _is_sha256(value):
            _add(blockers, "MEGA_PR02_BAD_PROTOCOL_HASH", f"{contract.protocol}.{field_name} is invalid")
    if contract.contract_reviewed_at_unix <= 0:
        _add(blockers, "MEGA_PR02_BAD_REVIEW_TIME", f"{contract.protocol} review time is invalid")
    if contract.contract_expires_at_unix <= contract.contract_reviewed_at_unix:
        _add(blockers, "MEGA_PR02_BAD_EXPIRY", f"{contract.protocol} expiry must follow review")
    if contract.disposition == ProtocolDisposition.ADMITTED and not contract.credentialed_probe_passed:
        _add(blockers, "MEGA_PR02_CREDENTIALED_PROBE_MISSING", f"{contract.protocol} probe must pass")
    if contract.stale_docs_admitted:
        _add(blockers, "MEGA_PR02_STALE_DOCS_ADMITTED", f"{contract.protocol} admits stale docs")
    if contract.arbitrary_env_truth_admitted:
        _add(blockers, "MEGA_PR02_ENV_TRUTH_ADMITTED", f"{contract.protocol} admits arbitrary env truth")
    if contract.unverified_constant_admitted:
        _add(blockers, "MEGA_PR02_UNVERIFIED_CONSTANT_ADMITTED", f"{contract.protocol} admits unverified constants")


def _validate_message_simulation(
    evidence: MessageSimulationEvidence,
    blockers: list[MegaPR02Violation],
) -> None:
    message_hashes = (
        evidence.compiled_v0_message_hash,
        evidence.simulation_input_message_hash,
        evidence.paper_acceptance_message_hash,
    )
    for field_name, value in (
        ("compiled_v0_message_hash", evidence.compiled_v0_message_hash),
        ("simulation_input_message_hash", evidence.simulation_input_message_hash),
        ("paper_acceptance_message_hash", evidence.paper_acceptance_message_hash),
        ("instruction_firewall_manifest_hash", evidence.instruction_firewall_manifest_hash),
        ("exact_simulation_report_hash", evidence.exact_simulation_report_hash),
        ("protocol_economics_report_hash", evidence.protocol_economics_report_hash),
    ):
        if not _is_sha256(value):
            _add(blockers, "MEGA_PR02_BAD_MESSAGE_HASH", f"{field_name} is invalid")
    if len(set(message_hashes)) != 1:
        _add(
            blockers,
            "MEGA_PR02_MESSAGE_HASH_MUTATED",
            "compiled, simulated and accepted message hashes must match",
        )
    if not evidence.fees_rent_slippage_tip_retry_complete:
        _add(blockers, "MEGA_PR02_ECONOMICS_INCOMPLETE", "fees/rent/slippage/tip/retry economics required")
    if evidence.mutation_after_simulation_detected:
        _add(blockers, "MEGA_PR02_MUTATION_AFTER_SIMULATION", "message mutation after simulation is forbidden")
    if not evidence.protocol_fee_sources_chain_or_contract_bound:
        _add(blockers, "MEGA_PR02_PROTOCOL_FEES_UNBOUND", "protocol fees must be chain/contract bound")
    if not evidence.paper_outcome_bound_to_message_hash:
        _add(blockers, "MEGA_PR02_OUTCOME_NOT_MESSAGE_BOUND", "paper outcome must bind exact message hash")


def _validate_hermetic_release(
    evidence: HermeticReleaseEvidence,
    blockers: list[MegaPR02Violation],
) -> None:
    for field_name, value in (
        ("source_export_manifest_hash", evidence.source_export_manifest_hash),
        ("hash_locked_wheelhouse_manifest_hash", evidence.hash_locked_wheelhouse_manifest_hash),
        ("sbom_hash", evidence.sbom_hash),
        ("provenance_hash", evidence.provenance_hash),
        ("release_signature_hash", evidence.release_signature_hash),
    ):
        if not _is_sha256(value):
            _add(blockers, "MEGA_PR02_BAD_RELEASE_HASH", f"{field_name} is invalid")
    if not evidence.clean_tree_verified:
        _add(blockers, "MEGA_PR02_DIRTY_SOURCE", "release requires clean VCS/export source")
    if not evidence.generated_artifacts_excluded:
        _add(blockers, "MEGA_PR02_GENERATED_ARTIFACTS_INCLUDED", "generated artifacts must be excluded")
    if not evidence.top_level_build_shadowing_prevented:
        _add(blockers, "MEGA_PR02_BUILD_SHADOWING", "top-level build/ shadowing must be prevented")
    if not evidence.aggregate_verifier_uses_isolated_environment:
        _add(blockers, "MEGA_PR02_AMBIENT_PYTHON", "aggregate verifier must use isolated environment")
    if not evidence.offline_build_network_disabled:
        _add(blockers, "MEGA_PR02_ONLINE_BUILD", "release build must run with network disabled")
    if not evidence.package_attestations_verified:
        _add(blockers, "MEGA_PR02_ATTESTATIONS_MISSING", "package attestations and hashes must verify")
    if not evidence.docker_base_image_pinned_by_digest:
        _add(blockers, "MEGA_PR02_IMAGE_NOT_DIGEST_PINNED", "base/runtime images must be digest pinned")
    if evidence.github_actions_total_uses < 0 or evidence.github_actions_full_sha_pins < 0:
        _add(blockers, "MEGA_PR02_BAD_ACTION_COUNTS", "GitHub Actions counts must be non-negative")
    if evidence.github_actions_full_sha_pins != evidence.github_actions_total_uses:
        _add(blockers, "MEGA_PR02_ACTIONS_NOT_PINNED", "all workflow action uses must be full-SHA pinned")
    if evidence.mutable_action_refs:
        _add(blockers, "MEGA_PR02_MUTABLE_ACTION_REFS", "mutable workflow action refs are forbidden")
    for ref in evidence.mutable_action_refs:
        if ACTION_PIN_RE.fullmatch(ref):
            _add(blockers, "MEGA_PR02_MUTABLE_REF_MISCLASSIFIED", "full-SHA refs must not be listed mutable")


def _validate_security_quality(
    evidence: SecurityQualityEvidence,
    blockers: list[MegaPR02Violation],
) -> None:
    scanners = set(evidence.mandatory_scanners)
    missing = [scanner for scanner in REQUIRED_SECURITY_SCANNERS if scanner not in scanners]
    if missing:
        _add(blockers, "MEGA_PR02_SECURITY_SCANNERS_MISSING", f"missing scanners: {', '.join(missing)}")
    for field_name, value in (
        ("scanner_policy_hash", evidence.scanner_policy_hash),
        ("lint_type_coverage_hash", evidence.lint_type_coverage_hash),
    ):
        if not _is_sha256(value):
            _add(blockers, "MEGA_PR02_BAD_SECURITY_HASH", f"{field_name} is invalid")
    if not evidence.path_aware_findings:
        _add(blockers, "MEGA_PR02_SECURITY_NOT_PATH_AWARE", "security findings must be path-aware")
    if not evidence.category_aware_findings:
        _add(blockers, "MEGA_PR02_SECURITY_NOT_CATEGORY_AWARE", "security findings must be category-aware")
    if not evidence.secrets_baseline_reviewed_or_removed:
        _add(blockers, "MEGA_PR02_SECRETS_BASELINE_UNREVIEWED", "secrets baseline must be reviewed or removed")
    if not evidence.pre_commit_dependencies_pinned:
        _add(blockers, "MEGA_PR02_PRECOMMIT_UNPINNED", "pre-commit dependencies must be pinned")
    if not evidence.security_gate_runs_in_clean_aggregate:
        _add(blockers, "MEGA_PR02_SECURITY_GATE_NOT_MANDATORY", "security gate must run in clean aggregate gate")
    if not evidence.runtime_asserts_replaced_on_critical_path:
        _add(blockers, "MEGA_PR02_RUNTIME_ASSERTS_REMAIN", "runtime asserts on critical path must be explicit validation")
    if not evidence.optimized_mode_tests_passed:
        _add(blockers, "MEGA_PR02_OPTIMIZED_TESTS_MISSING", "python -O tests must pass")
    if not evidence.no_python_o_validation_loss:
        _add(blockers, "MEGA_PR02_PYTHON_O_VALIDATION_LOSS", "python -O must not remove validation")


def _validate_sandbox_readiness(
    evidence: SandboxReadinessEvidence,
    blockers: list[MegaPR02Violation],
) -> None:
    for field_name, value in (
        ("apparmor_profile_hash", evidence.apparmor_profile_hash),
        ("seccomp_profile_hash", evidence.seccomp_profile_hash),
        ("egress_policy_hash", evidence.egress_policy_hash),
    ):
        if not _is_sha256(value):
            _add(blockers, "MEGA_PR02_BAD_SANDBOX_HASH", f"{field_name} is invalid")
    if not evidence.apparmor_loaded:
        _add(blockers, "MEGA_PR02_APPARMOR_NOT_LOADED", "AppArmor profile must be loaded")
    if not evidence.seccomp_loaded:
        _add(blockers, "MEGA_PR02_SECCOMP_NOT_LOADED", "seccomp profile must be loaded")
    if not evidence.destination_port_dns_egress_enforced:
        _add(blockers, "MEGA_PR02_EGRESS_NOT_ENFORCED", "destination/port/DNS egress must be enforced")
    if not evidence.secret_isolation_proven:
        _add(blockers, "MEGA_PR02_SECRET_ISOLATION_UNPROVEN", "secret isolation must be runtime-proven")
    tests = set(evidence.negative_runtime_tests)
    missing_tests = [test for test in REQUIRED_SANDBOX_NEGATIVE_TESTS if test not in tests]
    if missing_tests:
        _add(blockers, "MEGA_PR02_SANDBOX_NEGATIVE_TESTS_MISSING", f"missing sandbox tests: {', '.join(missing_tests)}")
    if not evidence.health_is_liveness_only:
        _add(blockers, "MEGA_PR02_HEALTH_SEMANTICS_AMBIGUOUS", "/health must remain liveness-only")
    if not evidence.readiness_endpoint_configured_for_admission:
        _add(blockers, "MEGA_PR02_READY_NOT_ADMISSION_GATE", "/ready must drive service admission")
    if not evidence.readiness_checks_worker_provider_db_queue_recovery:
        _add(blockers, "MEGA_PR02_READY_INCOMPLETE", "/ready must check worker/provider/DB/queue/recovery")
    if not evidence.readiness_false_on_critical_degradation:
        _add(blockers, "MEGA_PR02_READY_FAIL_OPEN", "/ready must become false on critical degradation")


def _validate_soak(
    evidence: SoakQualificationEvidence,
    blockers: list[MegaPR02Violation],
) -> None:
    if not isinstance(evidence.duration_hours, (int, float)) or not math.isfinite(evidence.duration_hours):
        _add(blockers, "MEGA_PR02_BAD_SOAK_DURATION", "soak duration must be finite")
    elif evidence.duration_hours < 72:
        _add(blockers, "MEGA_PR02_SOAK_TOO_SHORT", "release-bound soak must be at least 72 hours")
    for field_name, value in (
        ("source_commit_hash", evidence.source_commit_hash),
        ("wheel_hash", evidence.wheel_hash),
        ("image_digest_hash", evidence.image_digest_hash),
        ("config_digest_hash", evidence.config_digest_hash),
        ("contract_digest_hash", evidence.contract_digest_hash),
        ("evidence_bundle_hash", evidence.evidence_bundle_hash),
        ("slo_baseline_hash", evidence.slo_baseline_hash),
        ("chaos_dr_secret_rotation_report_hash", evidence.chaos_dr_secret_rotation_report_hash),
    ):
        if not _is_sha256(value):
            _add(blockers, "MEGA_PR02_BAD_SOAK_HASH", f"{field_name} is invalid")
    if not evidence.non_synthetic:
        _add(blockers, "MEGA_PR02_SYNTHETIC_SOAK", "soak must be non-synthetic")
    if not evidence.no_unexplained_terminal_state:
        _add(blockers, "MEGA_PR02_UNEXPLAINED_TERMINAL_STATE", "terminal states must be explained")
    if not evidence.no_duplicate_intent:
        _add(blockers, "MEGA_PR02_DUPLICATE_INTENT", "soak must contain no duplicate intents")
    if not evidence.no_synthetic_contamination:
        _add(blockers, "MEGA_PR02_SYNTHETIC_CONTAMINATION", "soak must not contain synthetic contamination")
    if not evidence.independent_review_signed:
        _add(blockers, "MEGA_PR02_REVIEW_UNSIGNED", "independent evidence review must be signed")
    if not evidence.product_state_changes_to_paper_ready_only:
        _add(blockers, "MEGA_PR02_WRONG_PRODUCT_STATE", "MEGA-PR-02 may only promote to paper-ready")


def _add(
    blockers: list[MegaPR02Violation],
    code: str,
    message: str,
) -> None:
    blockers.append(MegaPR02Violation(code=code, message=message))


def _dedupe(blockers: Iterable[MegaPR02Violation]) -> Iterable[MegaPR02Violation]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key not in seen:
            seen.add(key)
            yield blocker


def _is_sha256(value: str) -> bool:
    return isinstance(value, str) and HEX_64_RE.fullmatch(value) is not None


def _stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(_to_jsonable(value), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _to_jsonable(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _to_jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (tuple, list)):
        return [_to_jsonable(item) for item in value]
    return value
