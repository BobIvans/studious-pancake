"""PR-228 secret trust, signed state and release identity gate.

This module is an offline, sender-free acceptance contract for the Pass 8/9
PR-228 roadmap slice.  It validates materialized evidence for deny-by-default
secret roots, atomic secret reveal/revoke semantics, safe file acquisition,
external state trust anchors, crash-safe state publication, WORM retention and
exact release identity before any runtime can claim secret/control-plane
readiness.

It does not read secret files, decrypt credentials, open network sockets,
load private keys, sign state, publish state, purge evidence or enable live
execution.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any


SCHEMA_VERSION = "pr-228.secret-trust-release-identity.v1"

PR228_FINDINGS: tuple[str, ...] = tuple(
    [f"F-{number}" for number in range(424, 444)]
    + [f"F-{number}" for number in range(496, 501)]
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=-]{0,127}$")


class PR228State(StrEnum):
    """Stable review verdict for PR-228."""

    READY_FOR_SECRET_TRUST_REVIEW = "ready_for_secret_trust_review"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """Content-addressed evidence artifact reference."""

    label: str
    sha256: str
    path: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SecretRootPolicyEvidence:
    """Evidence for deny-by-default approved secret roots/providers."""

    empty_registry_denies_all_file_secrets: bool
    only_explicit_providers_and_roots_allowed: bool
    root_policy_binds_owner_mode_device_inode: bool
    owner_only_absolute_path_fallback_denied: bool
    provider_registry_generation_digest: str
    rollback_preserves_revocations: bool


@dataclass(frozen=True, slots=True)
class AtomicSecretLifecycleEvidence:
    """Evidence for reveal/revoke/max-use/lease/audit linearization."""

    reveal_revoke_max_uses_lease_audit_transactional: bool
    max_uses_one_concurrent_reveal_single_success: bool
    revoke_linearized_with_reveal: bool
    restart_preserves_revoke_and_use_count: bool
    lease_uses_trusted_time_not_wall_clock: bool
    audit_record_committed_with_reveal_decision: bool
    unknown_or_expired_lease_denied: bool


@dataclass(frozen=True, slots=True)
class SafeFileAcquisitionEvidence:
    """Evidence for no-follow, stable-inode, bounded secret acquisition."""

    openat_or_single_open_no_follow: bool
    owner_and_mode_verified: bool
    stable_inode_size_mtime_digest_before_after_read: bool
    byte_limit_enforced: bool
    no_check_then_open_path_reuse: bool
    symlink_swap_detected: bool
    content_swap_detected: bool
    version_derived_from_exact_bytes: bool


@dataclass(frozen=True, slots=True)
class SecretHandlingEvidence:
    """Evidence that secret values cannot escape as durable strings."""

    no_immutable_string_reveal: bool
    scoped_handle_or_mutable_buffer_api: bool
    best_effort_zeroization: bool
    secret_bytes_absent_from_logs_status_evidence: bool
    caller_cannot_set_secret_version: bool
    persistent_credential_lifecycle_registry: bool
    credential_records_immutable_or_cas_guarded: bool
    registry_has_concurrency_discipline: bool


@dataclass(frozen=True, slots=True)
class TrustAnchorEvidence:
    """Evidence for state trust root independence and continuity."""

    mac_or_signing_key_outside_runtime_state_dir: bool
    runtime_cannot_generate_own_state_trust_root: bool
    external_provenance_digest: str
    rotation_policy_materialized: bool
    revocation_policy_materialized: bool
    generation_continuity_independently_verifiable: bool


@dataclass(frozen=True, slots=True)
class ManagementReadinessEvidence:
    """Evidence for signed-state, management auth and readiness semantics."""

    signed_state_one_strict_nested_schema: bool
    malformed_nested_state_blocked: bool
    future_generation_blocked: bool
    active_signed_state_readers_unified_type_semantics: bool
    authenticated_proxy_identity_verified_not_boolean: bool
    bearer_auth_rate_limit_lockout_audit: bool
    liveness_derived_from_supervisor_truth: bool
    readiness_hash_covers_nested_schema: bool
    public_liveness_cannot_hardcode_ok: bool


@dataclass(frozen=True, slots=True)
class CrashSafePublicationEvidence:
    """Evidence for atomic state/archive publication."""

    temp_write_fsync_file_atomic_rename_fsync_dir: bool
    fsync_file_failure_blocks_publication: bool
    fsync_directory_failure_blocks_publication: bool
    permission_failure_blocks_readiness: bool
    crash_matrix_proves_previous_or_new_generation_only: bool
    torn_state_never_visible: bool


@dataclass(frozen=True, slots=True)
class RetentionReleaseEvidence:
    """Evidence for WORM retention and exact release identity."""

    completed_outbox_purge_requires_worm_receipt: bool
    worm_receipt_binds_payload_digest: bool
    retention_cutoff_validated_against_trusted_time_and_policy: bool
    retention_ledger_immutable_and_identity_complete: bool
    lifecycle_integrity_checks_materialized_attempt_projection: bool
    release_identity_binds_installed_wheel_image_config_trust_bundle: bool
    source_tree_only_release_identity_rejected: bool
    rollback_switches_trust_config_state_generation_atomically: bool


@dataclass(frozen=True, slots=True)
class PR228Evidence:
    """Complete PR-228 evidence bundle."""

    schema_version: str
    covered_findings: tuple[str, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    secret_roots: SecretRootPolicyEvidence
    lifecycle: AtomicSecretLifecycleEvidence
    safe_file: SafeFileAcquisitionEvidence
    handling: SecretHandlingEvidence
    trust_anchor: TrustAnchorEvidence
    management: ManagementReadinessEvidence
    publication: CrashSafePublicationEvidence
    retention_release: RetentionReleaseEvidence
    secret_reveal_requested: bool = False
    management_ready_requested: bool = False
    release_ready_requested: bool = False
    operational_paper_ready_requested: bool = False
    live_execution_requested: bool = False
    signer_requested: bool = False
    sender_requested: bool = False


@dataclass(frozen=True, slots=True)
class PR228Violation:
    """Stable fail-closed blocker."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class PR228Report:
    """Deterministic PR-228 review report."""

    schema_version: str
    state: PR228State
    blockers: tuple[PR228Violation, ...]
    covered_findings: tuple[str, ...]
    evidence_hash: str
    secret_trust_review_allowed: bool
    secret_reveal_allowed: bool
    management_ready_allowed: bool
    release_ready_allowed: bool
    operational_paper_ready_allowed: bool
    live_execution_allowed: bool
    signer_allowed: bool
    sender_allowed: bool

    def to_json(self) -> str:
        return _canonical_json(
            {
                "schema_version": self.schema_version,
                "state": self.state.value,
                "blockers": [asdict(blocker) for blocker in self.blockers],
                "covered_findings": list(self.covered_findings),
                "evidence_hash": self.evidence_hash,
                "secret_trust_review_allowed": self.secret_trust_review_allowed,
                "secret_reveal_allowed": self.secret_reveal_allowed,
                "management_ready_allowed": self.management_ready_allowed,
                "release_ready_allowed": self.release_ready_allowed,
                "operational_paper_ready_allowed": (
                    self.operational_paper_ready_allowed
                ),
                "live_execution_allowed": self.live_execution_allowed,
                "signer_allowed": self.signer_allowed,
                "sender_allowed": self.sender_allowed,
            }
        )


def evaluate_pr228_secret_trust_release_gate(
    evidence: PR228Evidence | Mapping[str, Any],
) -> PR228Report:
    """Evaluate PR-228 evidence without touching secrets or runtime state."""

    bundle = _coerce_evidence(evidence)
    blockers: list[PR228Violation] = []

    if bundle.schema_version != SCHEMA_VERSION:
        blockers.append(
            _blocker(
                "SCHEMA_VERSION_MISMATCH",
                f"expected {SCHEMA_VERSION}",
            )
        )

    _validate_findings(bundle, blockers)
    _validate_evidence_refs(bundle.evidence_refs, blockers)
    _validate_secret_roots(bundle.secret_roots, blockers)
    _validate_lifecycle(bundle.lifecycle, blockers)
    _validate_safe_file(bundle.safe_file, blockers)
    _validate_handling(bundle.handling, blockers)
    _validate_trust_anchor(bundle.trust_anchor, blockers)
    _validate_management(bundle.management, blockers)
    _validate_publication(bundle.publication, blockers)
    _validate_retention_release(bundle.retention_release, blockers)
    _validate_requested_capabilities(bundle, blockers)

    accepted = not blockers
    return PR228Report(
        schema_version=SCHEMA_VERSION,
        state=(
            PR228State.READY_FOR_SECRET_TRUST_REVIEW
            if accepted
            else PR228State.BLOCKED
        ),
        blockers=tuple(blockers),
        covered_findings=tuple(sorted(set(bundle.covered_findings))),
        evidence_hash=_hash_bundle(bundle),
        secret_trust_review_allowed=accepted,
        secret_reveal_allowed=False,
        management_ready_allowed=False,
        release_ready_allowed=False,
        operational_paper_ready_allowed=False,
        live_execution_allowed=False,
        signer_allowed=False,
        sender_allowed=False,
    )


def _validate_findings(
    evidence: PR228Evidence,
    blockers: list[PR228Violation],
) -> None:
    required = set(PR228_FINDINGS)
    actual = set(evidence.covered_findings)
    missing = sorted(required - actual)
    extra = sorted(actual - required)
    if missing:
        blockers.append(
            _blocker(
                "FINDING_COVERAGE_INCOMPLETE",
                f"missing findings: {','.join(missing)}",
            )
        )
    if extra:
        blockers.append(
            _blocker(
                "UNOWNED_FINDINGS_INCLUDED",
                f"unowned findings: {','.join(extra)}",
            )
        )


def _validate_evidence_refs(
    refs: Sequence[EvidenceRef],
    blockers: list[PR228Violation],
) -> None:
    labels = set()
    if len(refs) < 8:
        blockers.append(
            _blocker(
                "MATERIALIZED_EVIDENCE_INCOMPLETE",
                "every PR-228 workstream needs independent artifact evidence",
            )
        )
    for ref in refs:
        if ref.label in labels:
            blockers.append(_blocker("DUPLICATE_EVIDENCE_LABEL", ref.label))
        labels.add(ref.label)
        if not _SAFE_ID_RE.fullmatch(ref.label):
            blockers.append(_blocker("UNSAFE_EVIDENCE_LABEL", ref.label))
        if not _SHA256_RE.fullmatch(ref.sha256) or set(ref.sha256) == {"0"}:
            blockers.append(_blocker("INVALID_EVIDENCE_DIGEST", ref.label))
        if not ref.path.startswith("artifacts/pr228/"):
            blockers.append(_blocker("EVIDENCE_PATH_OUTSIDE_PR228", ref.path))
        lowered = ref.path.lower()
        if any(marker in lowered for marker in ("secret", "token", "key.pem")):
            blockers.append(
                _blocker(
                    "EVIDENCE_PATH_MAY_DISCLOSE_SECRET_LOCATOR",
                    ref.path,
                )
            )


def _validate_secret_roots(
    root: SecretRootPolicyEvidence,
    blockers: list[PR228Violation],
) -> None:
    required = {
        "empty_registry_denies_all_file_secrets": (
            root.empty_registry_denies_all_file_secrets
        ),
        "only_explicit_providers_and_roots_allowed": (
            root.only_explicit_providers_and_roots_allowed
        ),
        "root_policy_binds_owner_mode_device_inode": (
            root.root_policy_binds_owner_mode_device_inode
        ),
        "owner_only_absolute_path_fallback_denied": (
            root.owner_only_absolute_path_fallback_denied
        ),
        "rollback_preserves_revocations": root.rollback_preserves_revocations,
    }
    _require_all(required, "SECRET_ROOT_POLICY_INCOMPLETE", blockers)
    _require_sha(
        root.provider_registry_generation_digest,
        "SECRET_ROOT_REGISTRY_DIGEST_INVALID",
        blockers,
    )


def _validate_lifecycle(
    lifecycle: AtomicSecretLifecycleEvidence,
    blockers: list[PR228Violation],
) -> None:
    required = {
        "reveal_revoke_max_uses_lease_audit_transactional": (
            lifecycle.reveal_revoke_max_uses_lease_audit_transactional
        ),
        "max_uses_one_concurrent_reveal_single_success": (
            lifecycle.max_uses_one_concurrent_reveal_single_success
        ),
        "revoke_linearized_with_reveal": lifecycle.revoke_linearized_with_reveal,
        "restart_preserves_revoke_and_use_count": (
            lifecycle.restart_preserves_revoke_and_use_count
        ),
        "lease_uses_trusted_time_not_wall_clock": (
            lifecycle.lease_uses_trusted_time_not_wall_clock
        ),
        "audit_record_committed_with_reveal_decision": (
            lifecycle.audit_record_committed_with_reveal_decision
        ),
        "unknown_or_expired_lease_denied": lifecycle.unknown_or_expired_lease_denied,
    }
    _require_all(required, "SECRET_LIFECYCLE_NOT_LINEARIZED", blockers)


def _validate_safe_file(
    safe_file: SafeFileAcquisitionEvidence,
    blockers: list[PR228Violation],
) -> None:
    required = {
        "openat_or_single_open_no_follow": safe_file.openat_or_single_open_no_follow,
        "owner_and_mode_verified": safe_file.owner_and_mode_verified,
        "stable_inode_size_mtime_digest_before_after_read": (
            safe_file.stable_inode_size_mtime_digest_before_after_read
        ),
        "byte_limit_enforced": safe_file.byte_limit_enforced,
        "no_check_then_open_path_reuse": safe_file.no_check_then_open_path_reuse,
        "symlink_swap_detected": safe_file.symlink_swap_detected,
        "content_swap_detected": safe_file.content_swap_detected,
        "version_derived_from_exact_bytes": safe_file.version_derived_from_exact_bytes,
    }
    _require_all(required, "SAFE_FILE_ACQUISITION_INCOMPLETE", blockers)


def _validate_handling(
    handling: SecretHandlingEvidence,
    blockers: list[PR228Violation],
) -> None:
    required = {
        "no_immutable_string_reveal": handling.no_immutable_string_reveal,
        "scoped_handle_or_mutable_buffer_api": (
            handling.scoped_handle_or_mutable_buffer_api
        ),
        "best_effort_zeroization": handling.best_effort_zeroization,
        "secret_bytes_absent_from_logs_status_evidence": (
            handling.secret_bytes_absent_from_logs_status_evidence
        ),
        "caller_cannot_set_secret_version": handling.caller_cannot_set_secret_version,
        "persistent_credential_lifecycle_registry": (
            handling.persistent_credential_lifecycle_registry
        ),
        "credential_records_immutable_or_cas_guarded": (
            handling.credential_records_immutable_or_cas_guarded
        ),
        "registry_has_concurrency_discipline": (
            handling.registry_has_concurrency_discipline
        ),
    }
    _require_all(required, "SECRET_HANDLING_ESCAPES_CONTROL", blockers)


def _validate_trust_anchor(
    trust: TrustAnchorEvidence,
    blockers: list[PR228Violation],
) -> None:
    required = {
        "mac_or_signing_key_outside_runtime_state_dir": (
            trust.mac_or_signing_key_outside_runtime_state_dir
        ),
        "runtime_cannot_generate_own_state_trust_root": (
            trust.runtime_cannot_generate_own_state_trust_root
        ),
        "rotation_policy_materialized": trust.rotation_policy_materialized,
        "revocation_policy_materialized": trust.revocation_policy_materialized,
        "generation_continuity_independently_verifiable": (
            trust.generation_continuity_independently_verifiable
        ),
    }
    _require_all(required, "STATE_TRUST_ANCHOR_NOT_INDEPENDENT", blockers)
    _require_sha(
        trust.external_provenance_digest,
        "TRUST_ANCHOR_PROVENANCE_DIGEST_INVALID",
        blockers,
    )


def _validate_management(
    management: ManagementReadinessEvidence,
    blockers: list[PR228Violation],
) -> None:
    required = {
        "signed_state_one_strict_nested_schema": (
            management.signed_state_one_strict_nested_schema
        ),
        "malformed_nested_state_blocked": management.malformed_nested_state_blocked,
        "future_generation_blocked": management.future_generation_blocked,
        "active_signed_state_readers_unified_type_semantics": (
            management.active_signed_state_readers_unified_type_semantics
        ),
        "authenticated_proxy_identity_verified_not_boolean": (
            management.authenticated_proxy_identity_verified_not_boolean
        ),
        "bearer_auth_rate_limit_lockout_audit": (
            management.bearer_auth_rate_limit_lockout_audit
        ),
        "liveness_derived_from_supervisor_truth": (
            management.liveness_derived_from_supervisor_truth
        ),
        "readiness_hash_covers_nested_schema": (
            management.readiness_hash_covers_nested_schema
        ),
        "public_liveness_cannot_hardcode_ok": (
            management.public_liveness_cannot_hardcode_ok
        ),
    }
    _require_all(required, "MANAGEMENT_READINESS_CONTRACT_INCOMPLETE", blockers)


def _validate_publication(
    publication: CrashSafePublicationEvidence,
    blockers: list[PR228Violation],
) -> None:
    required = {
        "temp_write_fsync_file_atomic_rename_fsync_dir": (
            publication.temp_write_fsync_file_atomic_rename_fsync_dir
        ),
        "fsync_file_failure_blocks_publication": (
            publication.fsync_file_failure_blocks_publication
        ),
        "fsync_directory_failure_blocks_publication": (
            publication.fsync_directory_failure_blocks_publication
        ),
        "permission_failure_blocks_readiness": (
            publication.permission_failure_blocks_readiness
        ),
        "crash_matrix_proves_previous_or_new_generation_only": (
            publication.crash_matrix_proves_previous_or_new_generation_only
        ),
        "torn_state_never_visible": publication.torn_state_never_visible,
    }
    _require_all(required, "CRASH_SAFE_PUBLICATION_INCOMPLETE", blockers)


def _validate_retention_release(
    retention: RetentionReleaseEvidence,
    blockers: list[PR228Violation],
) -> None:
    required = {
        "completed_outbox_purge_requires_worm_receipt": (
            retention.completed_outbox_purge_requires_worm_receipt
        ),
        "worm_receipt_binds_payload_digest": retention.worm_receipt_binds_payload_digest,
        "retention_cutoff_validated_against_trusted_time_and_policy": (
            retention.retention_cutoff_validated_against_trusted_time_and_policy
        ),
        "retention_ledger_immutable_and_identity_complete": (
            retention.retention_ledger_immutable_and_identity_complete
        ),
        "lifecycle_integrity_checks_materialized_attempt_projection": (
            retention.lifecycle_integrity_checks_materialized_attempt_projection
        ),
        "release_identity_binds_installed_wheel_image_config_trust_bundle": (
            retention.release_identity_binds_installed_wheel_image_config_trust_bundle
        ),
        "source_tree_only_release_identity_rejected": (
            retention.source_tree_only_release_identity_rejected
        ),
        "rollback_switches_trust_config_state_generation_atomically": (
            retention.rollback_switches_trust_config_state_generation_atomically
        ),
    }
    _require_all(required, "RETENTION_RELEASE_IDENTITY_INCOMPLETE", blockers)


def _validate_requested_capabilities(
    evidence: PR228Evidence,
    blockers: list[PR228Violation],
) -> None:
    requested = {
        "secret_reveal_requested": evidence.secret_reveal_requested,
        "management_ready_requested": evidence.management_ready_requested,
        "release_ready_requested": evidence.release_ready_requested,
        "operational_paper_ready_requested": evidence.operational_paper_ready_requested,
        "live_execution_requested": evidence.live_execution_requested,
        "signer_requested": evidence.signer_requested,
        "sender_requested": evidence.sender_requested,
    }
    for name, value in requested.items():
        if value:
            blockers.append(
                _blocker(
                    "UNSAFE_CAPABILITY_REQUESTED",
                    f"{name} is outside this PR-228 review gate",
                )
            )


def _require_all(
    requirements: Mapping[str, bool],
    code: str,
    blockers: list[PR228Violation],
) -> None:
    missing = [name for name, ok in requirements.items() if not ok]
    if missing:
        blockers.append(_blocker(code, ",".join(missing)))


def _require_sha(
    value: str,
    code: str,
    blockers: list[PR228Violation],
) -> None:
    if not _SHA256_RE.fullmatch(value) or set(value) == {"0"}:
        blockers.append(_blocker(code, value))


def _hash_bundle(evidence: PR228Evidence) -> str:
    return hashlib.sha256(_canonical_json(_to_jsonable(evidence)).encode()).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {
            field: _to_jsonable(getattr(value, field))
            for field in value.__dataclass_fields__
        }
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    return value


def _coerce_evidence(value: PR228Evidence | Mapping[str, Any]) -> PR228Evidence:
    if isinstance(value, PR228Evidence):
        return value
    return PR228Evidence(
        schema_version=str(value["schema_version"]),
        covered_findings=tuple(value["covered_findings"]),
        evidence_refs=tuple(EvidenceRef(**item) for item in value["evidence_refs"]),
        secret_roots=SecretRootPolicyEvidence(**value["secret_roots"]),
        lifecycle=AtomicSecretLifecycleEvidence(**value["lifecycle"]),
        safe_file=SafeFileAcquisitionEvidence(**value["safe_file"]),
        handling=SecretHandlingEvidence(**value["handling"]),
        trust_anchor=TrustAnchorEvidence(**value["trust_anchor"]),
        management=ManagementReadinessEvidence(**value["management"]),
        publication=CrashSafePublicationEvidence(**value["publication"]),
        retention_release=RetentionReleaseEvidence(**value["retention_release"]),
        secret_reveal_requested=bool(value.get("secret_reveal_requested", False)),
        management_ready_requested=bool(value.get("management_ready_requested", False)),
        release_ready_requested=bool(value.get("release_ready_requested", False)),
        operational_paper_ready_requested=bool(
            value.get("operational_paper_ready_requested", False)
        ),
        live_execution_requested=bool(value.get("live_execution_requested", False)),
        signer_requested=bool(value.get("signer_requested", False)),
        sender_requested=bool(value.get("sender_requested", False)),
    )


def _blocker(code: str, message: str) -> PR228Violation:
    return PR228Violation(code=code, message=message)


__all__ = [
    "AtomicSecretLifecycleEvidence",
    "CrashSafePublicationEvidence",
    "EvidenceRef",
    "ManagementReadinessEvidence",
    "PR228Evidence",
    "PR228_FINDINGS",
    "PR228Report",
    "PR228State",
    "PR228Violation",
    "RetentionReleaseEvidence",
    "SCHEMA_VERSION",
    "SafeFileAcquisitionEvidence",
    "SecretHandlingEvidence",
    "SecretRootPolicyEvidence",
    "TrustAnchorEvidence",
    "evaluate_pr228_secret_trust_release_gate",
]
