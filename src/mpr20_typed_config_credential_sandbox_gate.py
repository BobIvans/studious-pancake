"""MPR-20 typed configuration, credential lifecycle and sandbox gate.

This module is intentionally side-effect-free. It does not read environment
variables, load secrets, inspect Docker, open files, call providers, open signer
IPC, or enable live execution. It defines the fail-closed evidence contract that
the real MPR-20 cutover must satisfy.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "mpr20.typed-config-credential-sandbox-gate.v1"

REQUIRED_FINDINGS: tuple[str, ...] = tuple(
    f"F-{number:03d}" for number in (*range(281, 297), *range(390, 404), *range(430, 435))
)

LIVE_EXECUTION_ALLOWED = False
SENDER_ALLOWED = False
SIGNER_ALLOWED = False

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class MPR20State(str, Enum):
    """Stable gate state values."""

    READY_FOR_TARGET_HOST_EVIDENCE = "ready_for_target_host_evidence"
    BLOCKED = "blocked"


class MPR20Blocker(str, Enum):
    """Stable fail-closed blocker codes."""

    MISSING_FINDING_COVERAGE = "MPR20_MISSING_FINDING_COVERAGE"
    DUPLICATE_FINDING_COVERAGE = "MPR20_DUPLICATE_FINDING_COVERAGE"
    MPR18_NOT_ACCEPTED = "MPR20_MPR18_NOT_ACCEPTED"
    BAD_CONFIG_HASH = "MPR20_BAD_CONFIG_HASH"
    CONFIG_CONTRACT_NOT_UNIFIED = "MPR20_CONFIG_CONTRACT_NOT_UNIFIED"
    UNKNOWN_INPUT_NOT_BLOCKED = "MPR20_UNKNOWN_INPUT_NOT_BLOCKED"
    CONFIG_PARSE_NOT_SAFE = "MPR20_CONFIG_PARSE_NOT_SAFE"
    LIVE_TRANSPORT_OR_COMMITMENT_PERMISSIVE = "MPR20_LIVE_TRANSPORT_OR_COMMITMENT_PERMISSIVE"
    PROGRAM_SELF_AUTHORIZATION = "MPR20_PROGRAM_SELF_AUTHORIZATION"
    RUNTIME_CAN_ACCESS_SIGNER_CREDENTIAL = "MPR20_RUNTIME_CAN_ACCESS_SIGNER_CREDENTIAL"
    CREDENTIAL_BACKEND_NOT_REAL = "MPR20_CREDENTIAL_BACKEND_NOT_REAL"
    CREDENTIAL_ROOT_OR_ROTATION_NOT_FAIL_CLOSED = "MPR20_CREDENTIAL_ROOT_OR_ROTATION_NOT_FAIL_CLOSED"
    CREDENTIAL_IDENTITY_LEAKS_RAW_BYTES = "MPR20_CREDENTIAL_IDENTITY_LEAKS_RAW_BYTES"
    SIGNER_ISOLATION_NOT_PROVEN = "MPR20_SIGNER_ISOLATION_NOT_PROVEN"
    BAD_CHAIN_REGISTRY_HASH = "MPR20_BAD_CHAIN_REGISTRY_HASH"
    CHAIN_OR_PROGRAM_IDENTITY_UNTRUSTED = "MPR20_CHAIN_OR_PROGRAM_IDENTITY_UNTRUSTED"
    DOCTOR_BYPASSES_HARDENED_TRANSPORT = "MPR20_DOCTOR_BYPASSES_HARDENED_TRANSPORT"
    DEPLOYMENT_SANDBOX_NOT_ATTESTED = "MPR20_DEPLOYMENT_SANDBOX_NOT_ATTESTED"
    UID_OR_VOLUME_NOT_ENFORCED = "MPR20_UID_OR_VOLUME_NOT_ENFORCED"
    APPARMOR_SECCOMP_NOT_ENFORCED = "MPR20_APPARMOR_SECCOMP_NOT_ENFORCED"
    EGRESS_NOT_ENFORCED = "MPR20_EGRESS_NOT_ENFORCED"
    DIAGNOSTICS_NOT_REDACTED = "MPR20_DIAGNOSTICS_NOT_REDACTED"
    LIVE_OR_SENDER_OR_SIGNER_REACHABLE = "MPR20_LIVE_OR_SENDER_OR_SIGNER_REACHABLE"


@dataclass(frozen=True, slots=True)
class MPR18DependencyEvidence:
    """Accepted MPR-18 artifact truth required before MPR-20 can be trusted."""

    mpr18_accepted: bool
    installed_artifact_manifest_sha256: str
    release_set_generation_sha256: str
    installed_surface_trace_sha256: str
    signer_split_manifest_sha256: str


@dataclass(frozen=True, slots=True)
class TypedConfigurationEvidence:
    """Fail-closed typed config contract for CLI/container/signer startup."""

    config_schema_sha256: str
    policy_bundle_sha256: str
    signed_activation_sha256: str
    cli_container_signer_contract_same: bool
    immutable_config_snapshot: bool
    unknown_flashloan_env_blocked: bool
    unknown_cluster_blocked: bool
    incompatible_secret_scheme_blocked: bool
    duplicate_keys_nan_yaml_bombs_blocked: bool
    secure_no_follow_open: bool
    bounded_read_before_parse: bool
    canonical_path_policy_enforced: bool
    weak_http_rpc_blocked: bool
    weak_ws_transport_blocked: bool
    weak_commitment_blocked: bool
    runtime_env_contract_matches_compose: bool


@dataclass(frozen=True, slots=True)
class CredentialLifecycleEvidence:
    """Credential and signer-secret lifecycle evidence."""

    secret_policy_sha256: str
    rotation_revocation_report_sha256: str
    docker_secret_contract_sha256: str
    network_runtime_has_signer_secret_access: bool
    signer_secret_resolved_only_in_signer_process: bool
    narrow_authenticated_ipc_required: bool
    empty_approved_roots_rejected: bool
    supported_backends_end_to_end_only: bool
    parse_only_keychain_contract_removed_or_implemented: bool
    secret_generation_content_bound: bool
    monotonic_secret_lease: bool
    maximum_use_cas_enforced: bool
    docker_secret_file_consumed: bool
    obsolete_variable_names_removed: bool
    raw_query_secret_forbidden_in_urls: bool
    raw_query_secret_forbidden_in_config_identity: bool
    revealed_secret_zeroization_boundary_documented: bool


@dataclass(frozen=True, slots=True)
class ChainProgramIdentityEvidence:
    """Canonical chain, cluster and program registry evidence."""

    chain_registry_sha256: str
    cluster_genesis_sha256: str
    program_registry_sha256: str
    commitment_policy_sha256: str
    https_wss_only: bool
    approved_finalized_or_rooted_commitment_only: bool
    unknown_cluster_rejected: bool
    configured_program_cannot_self_authorize: bool
    marginfi_program_bound_to_registry: bool
    token_programs_bound_to_registry: bool
    rpc_doctor_uses_hardened_transport: bool
    rpc_doctor_total_deadline: bool
    rpc_doctor_bounded_response: bool
    rpc_doctor_redacts_provider_errors: bool


@dataclass(frozen=True, slots=True)
class SandboxAttestationEvidence:
    """Target-host deployment sandbox and filesystem evidence."""

    target_host_attestation_sha256: str
    apparmor_profile_sha256: str
    seccomp_profile_sha256: str
    egress_policy_sha256: str
    volume_policy_sha256: str
    target_host_attested: bool
    runtime_uid: int
    volumes_writable_by_runtime_uid: bool
    canonical_db_log_archive_paths_volume_bound: bool
    apparmor_loaded_on_target_host: bool
    seccomp_loaded_on_target_host: bool
    sqlite_wal_fsync_syscalls_allowed: bool
    denied_syscall_tests_passed: bool
    internal_network_only: bool
    explicit_proxy_or_firewall_enforced: bool
    destination_allowlist_enforced: bool
    arbitrary_egress_denied: bool
    signer_network_separated_from_runtime: bool
    signer_mounts_separated_from_runtime: bool
    signer_user_separated_from_runtime: bool


@dataclass(frozen=True, slots=True)
class DiagnosticRedactionEvidence:
    """Bounded diagnostics and value-level redaction evidence."""

    diagnostic_corpus_sha256: str
    crash_log_corpus_sha256: str
    redaction_policy_sha256: str
    diagnostics_bounded_by_value_and_type: bool
    provider_payloads_removed: bool
    url_query_removed: bool
    filesystem_paths_minimized: bool
    secret_prefixes_removed: bool
    crash_logs_redacted: bool


@dataclass(frozen=True, slots=True)
class MPR20Evidence:
    """Complete MPR-20 checkpoint evidence."""

    covered_findings: tuple[str, ...]
    mpr18_dependency: MPR18DependencyEvidence
    typed_configuration: TypedConfigurationEvidence
    credential_lifecycle: CredentialLifecycleEvidence
    chain_program_identity: ChainProgramIdentityEvidence
    sandbox_attestation: SandboxAttestationEvidence
    diagnostic_redaction: DiagnosticRedactionEvidence
    live_execution_requested: bool = False
    sender_requested: bool = False
    signer_requested: bool = False


@dataclass(frozen=True, slots=True)
class MPR20Violation:
    """One stable fail-closed violation."""

    code: MPR20Blocker
    message: str


@dataclass(frozen=True, slots=True)
class MPR20Report:
    """Deterministic MPR-20 gate report."""

    schema_version: str
    state: MPR20State
    blockers: tuple[MPR20Violation, ...]
    evidence_hash: str
    required_findings: tuple[str, ...]
    startup_trust_boundary_ready: bool
    target_host_sandbox_evidence_ready: bool
    mpr21_mpr22_dependency_ready: bool
    live_execution_allowed: bool
    sender_allowed: bool
    signer_allowed: bool


def evaluate_mpr20_evidence(evidence: MPR20Evidence) -> MPR20Report:
    """Evaluate MPR-20 evidence without side effects."""

    blockers: list[MPR20Violation] = []
    _finding_coverage(evidence.covered_findings, blockers)
    _mpr18_dependency(evidence.mpr18_dependency, blockers)
    _typed_config(evidence.typed_configuration, blockers)
    _credentials(evidence.credential_lifecycle, blockers)
    _chain_program(evidence.chain_program_identity, blockers)
    _sandbox(evidence.sandbox_attestation, blockers)
    _diagnostics(evidence.diagnostic_redaction, blockers)

    if evidence.live_execution_requested or evidence.sender_requested or evidence.signer_requested:
        _add(
            blockers,
            MPR20Blocker.LIVE_OR_SENDER_OR_SIGNER_REACHABLE,
            "MPR-20 cannot enable live execution, sender I/O or signer access",
        )

    unique = tuple(_dedupe(blockers))
    ready = not unique
    return MPR20Report(
        schema_version=SCHEMA_VERSION,
        state=(
            MPR20State.READY_FOR_TARGET_HOST_EVIDENCE
            if ready
            else MPR20State.BLOCKED
        ),
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        required_findings=REQUIRED_FINDINGS,
        startup_trust_boundary_ready=ready,
        target_host_sandbox_evidence_ready=ready,
        mpr21_mpr22_dependency_ready=ready,
        live_execution_allowed=LIVE_EXECUTION_ALLOWED,
        sender_allowed=SENDER_ALLOWED,
        signer_allowed=SIGNER_ALLOWED,
    )


def blockers_by_code(report: MPR20Report) -> Mapping[MPR20Blocker, tuple[MPR20Violation, ...]]:
    """Group report blockers by stable code."""

    grouped: dict[MPR20Blocker, list[MPR20Violation]] = {}
    for blocker in report.blockers:
        grouped.setdefault(blocker.code, []).append(blocker)
    return {code: tuple(items) for code, items in grouped.items()}


def report_to_json(report: MPR20Report) -> str:
    """Serialize a report deterministically for evidence archives."""

    return json.dumps(_json(report), sort_keys=True, separators=(",", ":"))


def _finding_coverage(items: Sequence[str], out: list[MPR20Violation]) -> None:
    missing = [finding for finding in REQUIRED_FINDINGS if finding not in items]
    extras = [finding for finding in items if finding not in REQUIRED_FINDINGS]
    if missing or extras:
        _add(
            out,
            MPR20Blocker.MISSING_FINDING_COVERAGE,
            f"finding coverage mismatch: missing={missing}, extras={extras}",
        )
    if len(set(items)) != len(tuple(items)):
        _add(
            out,
            MPR20Blocker.DUPLICATE_FINDING_COVERAGE,
            "finding coverage must be unique",
        )


def _mpr18_dependency(dep: MPR18DependencyEvidence, out: list[MPR20Violation]) -> None:
    _hash_fields(
        out,
        MPR20Blocker.BAD_CONFIG_HASH,
        installed_artifact_manifest_sha256=dep.installed_artifact_manifest_sha256,
        release_set_generation_sha256=dep.release_set_generation_sha256,
        installed_surface_trace_sha256=dep.installed_surface_trace_sha256,
        signer_split_manifest_sha256=dep.signer_split_manifest_sha256,
    )
    if not dep.mpr18_accepted:
        _add(
            out,
            MPR20Blocker.MPR18_NOT_ACCEPTED,
            "MPR-20 requires accepted MPR-18 installed artifact truth",
        )


def _typed_config(cfg: TypedConfigurationEvidence, out: list[MPR20Violation]) -> None:
    _hash_fields(
        out,
        MPR20Blocker.BAD_CONFIG_HASH,
        config_schema_sha256=cfg.config_schema_sha256,
        policy_bundle_sha256=cfg.policy_bundle_sha256,
        signed_activation_sha256=cfg.signed_activation_sha256,
    )
    if not (cfg.cli_container_signer_contract_same and cfg.immutable_config_snapshot):
        _add(
            out,
            MPR20Blocker.CONFIG_CONTRACT_NOT_UNIFIED,
            "CLI/container/signer must share one immutable typed config contract",
        )
    unknown_flags = (
        cfg.unknown_flashloan_env_blocked,
        cfg.unknown_cluster_blocked,
        cfg.incompatible_secret_scheme_blocked,
    )
    if not all(unknown_flags):
        _add(
            out,
            MPR20Blocker.UNKNOWN_INPUT_NOT_BLOCKED,
            "unknown env, cluster and secret schemes must fail closed",
        )
    parse_flags = (
        cfg.duplicate_keys_nan_yaml_bombs_blocked,
        cfg.secure_no_follow_open,
        cfg.bounded_read_before_parse,
        cfg.canonical_path_policy_enforced,
    )
    if not all(parse_flags):
        _add(
            out,
            MPR20Blocker.CONFIG_PARSE_NOT_SAFE,
            "config loading must be bounded, canonical and no-follow",
        )
    transport_flags = (
        cfg.weak_http_rpc_blocked,
        cfg.weak_ws_transport_blocked,
        cfg.weak_commitment_blocked,
    )
    if not all(transport_flags):
        _add(
            out,
            MPR20Blocker.LIVE_TRANSPORT_OR_COMMITMENT_PERMISSIVE,
            "weak live transport or commitment fallback remains reachable",
        )
    if not cfg.runtime_env_contract_matches_compose:
        _add(
            out,
            MPR20Blocker.CONFIG_CONTRACT_NOT_UNIFIED,
            "runtime env contract must match deployment secret/config contract",
        )


def _credentials(creds: CredentialLifecycleEvidence, out: list[MPR20Violation]) -> None:
    _hash_fields(
        out,
        MPR20Blocker.CREDENTIAL_BACKEND_NOT_REAL,
        secret_policy_sha256=creds.secret_policy_sha256,
        rotation_revocation_report_sha256=creds.rotation_revocation_report_sha256,
        docker_secret_contract_sha256=creds.docker_secret_contract_sha256,
    )
    if creds.network_runtime_has_signer_secret_access:
        _add(
            out,
            MPR20Blocker.RUNTIME_CAN_ACCESS_SIGNER_CREDENTIAL,
            "network runtime must not resolve signer secret material",
        )
    isolation_flags = (
        creds.signer_secret_resolved_only_in_signer_process,
        creds.narrow_authenticated_ipc_required,
    )
    if not all(isolation_flags):
        _add(
            out,
            MPR20Blocker.SIGNER_ISOLATION_NOT_PROVEN,
            "signer secrets require isolated signer-only resolution and authenticated IPC",
        )
    backend_flags = (
        creds.supported_backends_end_to_end_only,
        creds.parse_only_keychain_contract_removed_or_implemented,
        creds.docker_secret_file_consumed,
        creds.obsolete_variable_names_removed,
    )
    if not all(backend_flags):
        _add(
            out,
            MPR20Blocker.CREDENTIAL_BACKEND_NOT_REAL,
            "secret backends and Docker secret files must be implemented end-to-end",
        )
    rotation_flags = (
        creds.empty_approved_roots_rejected,
        creds.secret_generation_content_bound,
        creds.monotonic_secret_lease,
        creds.maximum_use_cas_enforced,
    )
    if not all(rotation_flags):
        _add(
            out,
            MPR20Blocker.CREDENTIAL_ROOT_OR_ROTATION_NOT_FAIL_CLOSED,
            "secret roots, generations, leases and max-use CAS must fail closed",
        )
    leak_flags = (
        creds.raw_query_secret_forbidden_in_urls,
        creds.raw_query_secret_forbidden_in_config_identity,
        creds.revealed_secret_zeroization_boundary_documented,
    )
    if not all(leak_flags):
        _add(
            out,
            MPR20Blocker.CREDENTIAL_IDENTITY_LEAKS_RAW_BYTES,
            "raw query secrets or revealed secret bytes can enter durable identity",
        )


def _chain_program(chain: ChainProgramIdentityEvidence, out: list[MPR20Violation]) -> None:
    _hash_fields(
        out,
        MPR20Blocker.BAD_CHAIN_REGISTRY_HASH,
        chain_registry_sha256=chain.chain_registry_sha256,
        cluster_genesis_sha256=chain.cluster_genesis_sha256,
        program_registry_sha256=chain.program_registry_sha256,
        commitment_policy_sha256=chain.commitment_policy_sha256,
    )
    chain_flags = (
        chain.https_wss_only,
        chain.approved_finalized_or_rooted_commitment_only,
        chain.unknown_cluster_rejected,
        chain.marginfi_program_bound_to_registry,
        chain.token_programs_bound_to_registry,
    )
    if not all(chain_flags):
        _add(
            out,
            MPR20Blocker.CHAIN_OR_PROGRAM_IDENTITY_UNTRUSTED,
            "chain, cluster, commitment and program identities must be registry-bound",
        )
    if not chain.configured_program_cannot_self_authorize:
        _add(
            out,
            MPR20Blocker.PROGRAM_SELF_AUTHORIZATION,
            "configured program ID cannot authorize itself into the allowlist",
        )
    doctor_flags = (
        chain.rpc_doctor_uses_hardened_transport,
        chain.rpc_doctor_total_deadline,
        chain.rpc_doctor_bounded_response,
        chain.rpc_doctor_redacts_provider_errors,
    )
    if not all(doctor_flags):
        _add(
            out,
            MPR20Blocker.DOCTOR_BYPASSES_HARDENED_TRANSPORT,
            "startup RPC doctor must use the hardened transport and bounded redaction model",
        )


def _sandbox(sandbox: SandboxAttestationEvidence, out: list[MPR20Violation]) -> None:
    _hash_fields(
        out,
        MPR20Blocker.DEPLOYMENT_SANDBOX_NOT_ATTESTED,
        target_host_attestation_sha256=sandbox.target_host_attestation_sha256,
        apparmor_profile_sha256=sandbox.apparmor_profile_sha256,
        seccomp_profile_sha256=sandbox.seccomp_profile_sha256,
        egress_policy_sha256=sandbox.egress_policy_sha256,
        volume_policy_sha256=sandbox.volume_policy_sha256,
    )
    if not sandbox.target_host_attested:
        _add(
            out,
            MPR20Blocker.DEPLOYMENT_SANDBOX_NOT_ATTESTED,
            "sandbox controls require measured target-host attestation",
        )
    volume_flags = (
        sandbox.runtime_uid == 10001,
        sandbox.volumes_writable_by_runtime_uid,
        sandbox.canonical_db_log_archive_paths_volume_bound,
    )
    if not all(volume_flags):
        _add(
            out,
            MPR20Blocker.UID_OR_VOLUME_NOT_ENFORCED,
            "UID 10001 volumes and canonical DB/log/archive paths must be enforced",
        )
    profile_flags = (
        sandbox.apparmor_loaded_on_target_host,
        sandbox.seccomp_loaded_on_target_host,
        sandbox.sqlite_wal_fsync_syscalls_allowed,
        sandbox.denied_syscall_tests_passed,
    )
    if not all(profile_flags):
        _add(
            out,
            MPR20Blocker.APPARMOR_SECCOMP_NOT_ENFORCED,
            "AppArmor/seccomp must be loaded and proven with SQLite/WAL and deny tests",
        )
    egress_flags = (
        sandbox.internal_network_only,
        sandbox.explicit_proxy_or_firewall_enforced,
        sandbox.destination_allowlist_enforced,
        sandbox.arbitrary_egress_denied,
    )
    if not all(egress_flags):
        _add(
            out,
            MPR20Blocker.EGRESS_NOT_ENFORCED,
            "egress must be deny-by-default and enforceable on the target host",
        )
    split_flags = (
        sandbox.signer_network_separated_from_runtime,
        sandbox.signer_mounts_separated_from_runtime,
        sandbox.signer_user_separated_from_runtime,
    )
    if not all(split_flags):
        _add(
            out,
            MPR20Blocker.SIGNER_ISOLATION_NOT_PROVEN,
            "runtime and signer must be separated by network, mounts and user",
        )


def _diagnostics(diag: DiagnosticRedactionEvidence, out: list[MPR20Violation]) -> None:
    _hash_fields(
        out,
        MPR20Blocker.DIAGNOSTICS_NOT_REDACTED,
        diagnostic_corpus_sha256=diag.diagnostic_corpus_sha256,
        crash_log_corpus_sha256=diag.crash_log_corpus_sha256,
        redaction_policy_sha256=diag.redaction_policy_sha256,
    )
    diagnostic_flags = (
        diag.diagnostics_bounded_by_value_and_type,
        diag.provider_payloads_removed,
        diag.url_query_removed,
        diag.filesystem_paths_minimized,
        diag.secret_prefixes_removed,
        diag.crash_logs_redacted,
    )
    if not all(diagnostic_flags):
        _add(
            out,
            MPR20Blocker.DIAGNOSTICS_NOT_REDACTED,
            "diagnostics and crash logs must be bounded and value-redacted",
        )


def _hash_fields(
    out: list[MPR20Violation],
    blocker: MPR20Blocker,
    **values: str,
) -> None:
    for name, value in values.items():
        if not _sha256(value):
            _add(out, blocker, f"{name} must be a non-placeholder sha256")


def _sha256(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value)) and value not in {
        "0" * 64,
        "f" * 64,
    }


def _stable_hash(value: object) -> str:
    payload = json.dumps(_json(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {name: _json(item) for name, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_json(item) for item in value]
    return value


def _add(out: list[MPR20Violation], code: MPR20Blocker, message: str) -> None:
    out.append(MPR20Violation(code=code, message=message))


def _dedupe(blockers: Iterable[MPR20Violation]) -> Iterable[MPR20Violation]:
    seen: set[tuple[MPR20Blocker, str]] = set()
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key not in seen:
            seen.add(key)
            yield blocker
