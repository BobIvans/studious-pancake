"""MPR-09 live configuration, credential lifecycle and deployment sandbox gate.

This module is intentionally offline.  It does not read secrets, open Docker
resources, contact RPC endpoints or enable live trading.  It turns the V6
MPR-09 production-readiness findings into a deterministic fail-closed evidence
contract so unsafe live/deployment claims cannot be promoted as release truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Mapping
from urllib.parse import urlparse

SCHEMA_VERSION = "mpr09.live-configuration-deployment-sandbox-gate.v1"
LIVE_EXECUTION_ALLOWED = False
SIGNER_ACCESS_ALLOWED = False
PROVIDER_NETWORK_ALLOWED = False

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CLUSTER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")


class MPR09Blocker(StrEnum):
    """Stable blocker codes emitted by the MPR-09 evidence gate."""

    MPR08_LEDGER_NOT_ACCEPTED = "MPR08_LEDGER_NOT_ACCEPTED"
    LIVE_AUTHORITY_NOT_FINALIZED = "LIVE_AUTHORITY_NOT_FINALIZED"
    PLAINTEXT_RPC_TRANSPORT = "PLAINTEXT_RPC_TRANSPORT"
    UNKNOWN_CLUSTER_OR_GENESIS = "UNKNOWN_CLUSTER_OR_GENESIS"
    SELF_AUTHORIZED_PROTOCOL_PROGRAM = "SELF_AUTHORIZED_PROTOCOL_PROGRAM"
    SECRET_GENERATION_NOT_CONTENT_BOUND = "SECRET_GENERATION_NOT_CONTENT_BOUND"
    SECRET_ROOT_POLICY_FAIL_OPEN = "SECRET_ROOT_POLICY_FAIL_OPEN"
    CREDENTIAL_AUTHORITY_NOT_DURABLE = "CREDENTIAL_AUTHORITY_NOT_DURABLE"
    LEASE_TIME_NOT_DUAL_DOMAIN = "LEASE_TIME_NOT_DUAL_DOMAIN"
    SECRET_CONSUMPTION_NOT_SERIALIZED = "SECRET_CONSUMPTION_NOT_SERIALIZED"
    SECRET_STRINGS_EXPOSED = "SECRET_STRINGS_EXPOSED"
    SECRET_MOUNT_NOT_CONSUMED = "SECRET_MOUNT_NOT_CONSUMED"
    LEGACY_FLAGS_WITHOUT_TYPED_MODE = "LEGACY_FLAGS_WITHOUT_TYPED_MODE"
    EGRESS_NOT_ENFORCED = "EGRESS_NOT_ENFORCED"
    DURABLE_VOLUME_NOT_PROVEN = "DURABLE_VOLUME_NOT_PROVEN"
    SANDBOX_PROFILE_NOT_ATTESTED = "SANDBOX_PROFILE_NOT_ATTESTED"
    HEALTHCHECK_NOT_READINESS = "HEALTHCHECK_NOT_READINESS"
    LIVE_OR_SIGNER_REACHABLE = "LIVE_OR_SIGNER_REACHABLE"


class MPR09EvidenceError(ValueError):
    """Raised when MPR-09 evidence is malformed."""


@dataclass(frozen=True, slots=True)
class LiveRuntimeConfigEvidence:
    """Live authority configuration and protocol identity evidence."""

    runtime_mode: str
    authoritative_commitment: str
    discovery_commitment: str
    rpc_http_url: str
    rpc_ws_url: str
    cluster_name: str
    cluster_genesis_sha256: str
    cluster_registry_sha256: str
    protocol_registry_sha256: str
    marginfi_program_id: str
    marginfi_program_from_signed_registry: bool
    config_can_extend_program_allowlist: bool = False

    def __post_init__(self) -> None:
        _runtime_mode(self.runtime_mode, "runtime_mode")
        _commitment(self.authoritative_commitment, "authoritative_commitment")
        _commitment(self.discovery_commitment, "discovery_commitment")
        _url(self.rpc_http_url, "rpc_http_url")
        _url(self.rpc_ws_url, "rpc_ws_url")
        _cluster(self.cluster_name, "cluster_name")
        _sha256(self.cluster_genesis_sha256, "cluster_genesis_sha256")
        _sha256(self.cluster_registry_sha256, "cluster_registry_sha256")
        _sha256(self.protocol_registry_sha256, "protocol_registry_sha256")
        _stable_id(self.marginfi_program_id, "marginfi_program_id")


@dataclass(frozen=True, slots=True)
class CredentialLifecycleEvidence:
    """Durable, cross-process credential version and lease evidence."""

    credential_registry_sha256: str
    credential_generation_sha256: str
    secret_mount_schema_sha256: str
    secret_values_redacted: bool
    generation_changes_on_rotation: bool
    revocation_durable_cross_process: bool
    restart_cannot_resurrect_revoked_generation: bool
    leases_use_monotonic_and_trusted_utc: bool
    boot_generation_bound_to_lease: bool
    max_use_consumption_serialized: bool
    raw_secret_strings_exposed_to_runtime: bool
    approved_file_roots_required: bool
    arbitrary_owner_file_read_allowed: bool
    content_bound_generation_ids: bool

    def __post_init__(self) -> None:
        _sha256(self.credential_registry_sha256, "credential_registry_sha256")
        _sha256(self.credential_generation_sha256, "credential_generation_sha256")
        _sha256(self.secret_mount_schema_sha256, "secret_mount_schema_sha256")


@dataclass(frozen=True, slots=True)
class DeploymentSandboxEvidence:
    """Measured container/deployment sandbox evidence for MPR-09."""

    deployment_policy_sha256: str
    typed_runtime_mode_configured: bool
    legacy_flags_only: bool
    runtime_env_secret_mounted: bool
    application_reads_secret_mount: bool
    raw_secret_env_vars_present: bool
    egress_policy_enforced_by_runtime_topology: bool
    denied_destination_probe_passed: bool
    approved_destination_probe_passed: bool
    arbitrary_bridge_network_available: bool
    canonical_state_paths_on_persistent_volumes: bool
    non_root_volume_write_restart_probe_passed: bool
    apparmor_profile_hash_sha256: str
    apparmor_profile_loaded: bool
    readiness_uses_workload_state: bool
    orchestrator_uses_ready_not_health: bool
    liveness_and_readiness_separated: bool

    def __post_init__(self) -> None:
        _sha256(self.deployment_policy_sha256, "deployment_policy_sha256")
        _sha256(self.apparmor_profile_hash_sha256, "apparmor_profile_hash_sha256")


@dataclass(frozen=True, slots=True)
class MPR09LiveDeploymentEvidence:
    """Top-level MPR-09 evidence envelope."""

    mpr08_completion_ledger_accepted: bool
    mpr08_completion_ledger_sha256: str
    live_config: LiveRuntimeConfigEvidence
    credential_lifecycle: CredentialLifecycleEvidence
    deployment_sandbox: DeploymentSandboxEvidence
    live_execution_reachable: bool = False
    signer_access_reachable: bool = False
    provider_network_calls_performed: bool = False

    def __post_init__(self) -> None:
        _sha256(self.mpr08_completion_ledger_sha256, "mpr08_completion_ledger_sha256")


@dataclass(frozen=True, slots=True)
class MPR09LiveDeploymentReport:
    """Deterministic report emitted by the MPR-09 gate."""

    schema_version: str
    ready: bool
    blockers: tuple[str, ...]
    evidence_hash: str
    live_execution_allowed: bool = LIVE_EXECUTION_ALLOWED
    signer_access_allowed: bool = SIGNER_ACCESS_ALLOWED
    provider_network_allowed: bool = PROVIDER_NETWORK_ALLOWED

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ready": self.ready,
            "blockers": list(self.blockers),
            "evidence_hash": self.evidence_hash,
            "live_execution_allowed": self.live_execution_allowed,
            "signer_access_allowed": self.signer_access_allowed,
            "provider_network_allowed": self.provider_network_allowed,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def evaluate_mpr09_live_deployment(
    evidence: MPR09LiveDeploymentEvidence,
) -> MPR09LiveDeploymentReport:
    """Evaluate MPR-09 live configuration and deployment evidence."""

    blockers: list[MPR09Blocker] = []
    if not evidence.mpr08_completion_ledger_accepted:
        blockers.append(MPR09Blocker.MPR08_LEDGER_NOT_ACCEPTED)
    if (
        evidence.live_execution_reachable
        or evidence.signer_access_reachable
        or evidence.provider_network_calls_performed
    ):
        blockers.append(MPR09Blocker.LIVE_OR_SIGNER_REACHABLE)

    config = evidence.live_config
    if config.runtime_mode == "live" and config.authoritative_commitment != "finalized":
        blockers.append(MPR09Blocker.LIVE_AUTHORITY_NOT_FINALIZED)
    if not _is_tls_rpc(config.rpc_http_url, "https") or not _is_tls_rpc(
        config.rpc_ws_url,
        "wss",
    ):
        blockers.append(MPR09Blocker.PLAINTEXT_RPC_TRANSPORT)
    if (
        config.cluster_name not in {"mainnet-beta", "devnet", "testnet"}
        or config.cluster_name != "mainnet-beta"
        or config.cluster_genesis_sha256 == config.cluster_registry_sha256
    ):
        blockers.append(MPR09Blocker.UNKNOWN_CLUSTER_OR_GENESIS)
    if (
        not config.marginfi_program_from_signed_registry
        or config.config_can_extend_program_allowlist
    ):
        blockers.append(MPR09Blocker.SELF_AUTHORIZED_PROTOCOL_PROGRAM)

    lifecycle = evidence.credential_lifecycle
    if not (
        lifecycle.generation_changes_on_rotation
        and lifecycle.content_bound_generation_ids
    ):
        blockers.append(MPR09Blocker.SECRET_GENERATION_NOT_CONTENT_BOUND)
    if (
        not lifecycle.approved_file_roots_required
        or lifecycle.arbitrary_owner_file_read_allowed
    ):
        blockers.append(MPR09Blocker.SECRET_ROOT_POLICY_FAIL_OPEN)
    if not (
        lifecycle.revocation_durable_cross_process
        and lifecycle.restart_cannot_resurrect_revoked_generation
    ):
        blockers.append(MPR09Blocker.CREDENTIAL_AUTHORITY_NOT_DURABLE)
    if not (
        lifecycle.leases_use_monotonic_and_trusted_utc
        and lifecycle.boot_generation_bound_to_lease
    ):
        blockers.append(MPR09Blocker.LEASE_TIME_NOT_DUAL_DOMAIN)
    if not lifecycle.max_use_consumption_serialized:
        blockers.append(MPR09Blocker.SECRET_CONSUMPTION_NOT_SERIALIZED)
    if lifecycle.raw_secret_strings_exposed_to_runtime or not lifecycle.secret_values_redacted:
        blockers.append(MPR09Blocker.SECRET_STRINGS_EXPOSED)

    sandbox = evidence.deployment_sandbox
    if not (
        sandbox.runtime_env_secret_mounted
        and sandbox.application_reads_secret_mount
        and not sandbox.raw_secret_env_vars_present
    ):
        blockers.append(MPR09Blocker.SECRET_MOUNT_NOT_CONSUMED)
    if not sandbox.typed_runtime_mode_configured or sandbox.legacy_flags_only:
        blockers.append(MPR09Blocker.LEGACY_FLAGS_WITHOUT_TYPED_MODE)
    if not (
        sandbox.egress_policy_enforced_by_runtime_topology
        and sandbox.denied_destination_probe_passed
        and sandbox.approved_destination_probe_passed
        and not sandbox.arbitrary_bridge_network_available
    ):
        blockers.append(MPR09Blocker.EGRESS_NOT_ENFORCED)
    if not (
        sandbox.canonical_state_paths_on_persistent_volumes
        and sandbox.non_root_volume_write_restart_probe_passed
    ):
        blockers.append(MPR09Blocker.DURABLE_VOLUME_NOT_PROVEN)
    if not sandbox.apparmor_profile_loaded:
        blockers.append(MPR09Blocker.SANDBOX_PROFILE_NOT_ATTESTED)
    if not (
        sandbox.readiness_uses_workload_state
        and sandbox.orchestrator_uses_ready_not_health
        and sandbox.liveness_and_readiness_separated
    ):
        blockers.append(MPR09Blocker.HEALTHCHECK_NOT_READINESS)

    blocker_values = tuple(sorted({blocker.value for blocker in blockers}))
    return MPR09LiveDeploymentReport(
        schema_version=SCHEMA_VERSION,
        ready=not blocker_values,
        blockers=blocker_values,
        evidence_hash=_stable_hash(evidence_to_dict(evidence)),
    )


def evidence_to_dict(evidence: MPR09LiveDeploymentEvidence) -> dict[str, object]:
    """Return a deterministic JSON-compatible evidence payload."""

    config = evidence.live_config
    lifecycle = evidence.credential_lifecycle
    sandbox = evidence.deployment_sandbox
    return {
        "mpr08_completion_ledger_accepted": evidence.mpr08_completion_ledger_accepted,
        "mpr08_completion_ledger_sha256": evidence.mpr08_completion_ledger_sha256,
        "live_execution_reachable": evidence.live_execution_reachable,
        "signer_access_reachable": evidence.signer_access_reachable,
        "provider_network_calls_performed": evidence.provider_network_calls_performed,
        "live_config": {
            "runtime_mode": config.runtime_mode,
            "authoritative_commitment": config.authoritative_commitment,
            "discovery_commitment": config.discovery_commitment,
            "rpc_http_url": config.rpc_http_url,
            "rpc_ws_url": config.rpc_ws_url,
            "cluster_name": config.cluster_name,
            "cluster_genesis_sha256": config.cluster_genesis_sha256,
            "cluster_registry_sha256": config.cluster_registry_sha256,
            "protocol_registry_sha256": config.protocol_registry_sha256,
            "marginfi_program_id": config.marginfi_program_id,
            "marginfi_program_from_signed_registry": config.marginfi_program_from_signed_registry,
            "config_can_extend_program_allowlist": config.config_can_extend_program_allowlist,
        },
        "credential_lifecycle": {
            "credential_registry_sha256": lifecycle.credential_registry_sha256,
            "credential_generation_sha256": lifecycle.credential_generation_sha256,
            "secret_mount_schema_sha256": lifecycle.secret_mount_schema_sha256,
            "secret_values_redacted": lifecycle.secret_values_redacted,
            "generation_changes_on_rotation": lifecycle.generation_changes_on_rotation,
            "revocation_durable_cross_process": lifecycle.revocation_durable_cross_process,
            "restart_cannot_resurrect_revoked_generation": lifecycle.restart_cannot_resurrect_revoked_generation,
            "leases_use_monotonic_and_trusted_utc": lifecycle.leases_use_monotonic_and_trusted_utc,
            "boot_generation_bound_to_lease": lifecycle.boot_generation_bound_to_lease,
            "max_use_consumption_serialized": lifecycle.max_use_consumption_serialized,
            "raw_secret_strings_exposed_to_runtime": lifecycle.raw_secret_strings_exposed_to_runtime,
            "approved_file_roots_required": lifecycle.approved_file_roots_required,
            "arbitrary_owner_file_read_allowed": lifecycle.arbitrary_owner_file_read_allowed,
            "content_bound_generation_ids": lifecycle.content_bound_generation_ids,
        },
        "deployment_sandbox": {
            "deployment_policy_sha256": sandbox.deployment_policy_sha256,
            "typed_runtime_mode_configured": sandbox.typed_runtime_mode_configured,
            "legacy_flags_only": sandbox.legacy_flags_only,
            "runtime_env_secret_mounted": sandbox.runtime_env_secret_mounted,
            "application_reads_secret_mount": sandbox.application_reads_secret_mount,
            "raw_secret_env_vars_present": sandbox.raw_secret_env_vars_present,
            "egress_policy_enforced_by_runtime_topology": sandbox.egress_policy_enforced_by_runtime_topology,
            "denied_destination_probe_passed": sandbox.denied_destination_probe_passed,
            "approved_destination_probe_passed": sandbox.approved_destination_probe_passed,
            "arbitrary_bridge_network_available": sandbox.arbitrary_bridge_network_available,
            "canonical_state_paths_on_persistent_volumes": sandbox.canonical_state_paths_on_persistent_volumes,
            "non_root_volume_write_restart_probe_passed": sandbox.non_root_volume_write_restart_probe_passed,
            "apparmor_profile_hash_sha256": sandbox.apparmor_profile_hash_sha256,
            "apparmor_profile_loaded": sandbox.apparmor_profile_loaded,
            "readiness_uses_workload_state": sandbox.readiness_uses_workload_state,
            "orchestrator_uses_ready_not_health": sandbox.orchestrator_uses_ready_not_health,
            "liveness_and_readiness_separated": sandbox.liveness_and_readiness_separated,
        },
    }


def _stable_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _sha256(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise MPR09EvidenceError(f"{name} must be a lowercase sha256 hex digest")
    if value in {"0" * 64, "f" * 64}:
        raise MPR09EvidenceError(f"{name} must not be a placeholder digest")


def _stable_id(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise MPR09EvidenceError(f"{name} must be a stable non-empty identifier")


def _cluster(value: str, name: str) -> None:
    if not isinstance(value, str) or not _CLUSTER_RE.fullmatch(value):
        raise MPR09EvidenceError(f"{name} must be a normalized cluster name")


def _commitment(value: str, name: str) -> None:
    if value not in {"processed", "confirmed", "finalized"}:
        raise MPR09EvidenceError(f"{name} must be processed, confirmed or finalized")


def _runtime_mode(value: str, name: str) -> None:
    if value not in {"safe-idle", "paper", "shadow", "live"}:
        raise MPR09EvidenceError(f"{name} must be a supported runtime mode")


def _url(value: str, name: str) -> None:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise MPR09EvidenceError(f"{name} must be an absolute URL")


def _is_tls_rpc(value: str, expected_scheme: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == expected_scheme and bool(parsed.netloc)
