"""PR-151 isolated signer, finalized settlement, and reviewed release gate.

This module is intentionally side-effect free.  It validates the evidence that
would be required before a reviewed live-canary path can even be considered, but
it never signs, submits, polls, resends, enables live, or imports key material.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum, StrEnum
import hashlib
import json
import re
from typing import Any

PR151_RELEASE_PATH_SCHEMA = "pr151.isolated-signer-finalized-release-path.v1"
PR151_RELEASE_PATH_RESULT_SCHEMA = "pr151.isolated-signer-finalized-release-result.v1"
PR150_SOAK_EVIDENCE_NAME = "pr150.sender-free-paper-soak-evidence"
MAX_FULL_WIRE_TRANSACTION_BYTES = 1232
REQUIRED_RELEASE_SIGNOFFS = (
    "release-owner-signoff",
    "security-owner-signoff",
    "risk-owner-signoff",
    "operator-final-arm-signoff",
)
SUPPORTED_SIGNER_BACKENDS = frozenset({"kms", "hsm", "vault", "keychain"})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class PR151ReleasePathError(ValueError):
    """Raised when PR-151 release-path evidence is malformed."""


class PR151ReleasePathState(StrEnum):
    """Fail-closed readiness states for the reviewed release path."""

    BLOCKED = "blocked"
    READY_FOR_MANUAL_RELEASE_REVIEW = "ready-for-manual-release-review"


@dataclass(frozen=True, slots=True)
class PR151EvidenceRef:
    name: str
    sha256: str
    source_commit: str
    passed: bool
    human_reviewed: bool
    reviewer: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise PR151ReleasePathError("evidence.name is required")
        object.__setattr__(self, "sha256", _require_sha256(self.sha256, "sha256"))
        object.__setattr__(
            self,
            "source_commit",
            _require_git_sha(self.source_commit, "source_commit"),
        )
        _require_bool(self.passed, "evidence.passed")
        _require_bool(self.human_reviewed, "evidence.human_reviewed")
        if self.human_reviewed and not self.reviewer.strip():
            raise PR151ReleasePathError("reviewed evidence must include reviewer")


@dataclass(frozen=True, slots=True)
class IsolatedSignerBoundary:
    backend_kind: str
    network_runtime_imports_keypair: bool
    signer_has_general_network_access: bool
    parses_message_independently: bool
    derives_payer_signers_programs_accounts: bool
    verifies_policy_and_proof_hashes: bool
    verifies_full_wire_transaction_limit: bool
    returns_signature_only: bool
    max_full_wire_bytes: int = MAX_FULL_WIRE_TRANSACTION_BYTES

    def __post_init__(self) -> None:
        if self.backend_kind not in SUPPORTED_SIGNER_BACKENDS:
            raise PR151ReleasePathError("unsupported signer backend")
        for field_name in (
            "network_runtime_imports_keypair",
            "signer_has_general_network_access",
            "parses_message_independently",
            "derives_payer_signers_programs_accounts",
            "verifies_policy_and_proof_hashes",
            "verifies_full_wire_transaction_limit",
            "returns_signature_only",
        ):
            _require_bool(getattr(self, field_name), field_name)
        if self.max_full_wire_bytes != MAX_FULL_WIRE_TRANSACTION_BYTES:
            raise PR151ReleasePathError("full wire transaction limit must be 1232 bytes")


@dataclass(frozen=True, slots=True)
class DurableAuthorizationPolicy:
    policy_bundle_sha256: str
    transaction_proof_sha256: str
    signer_readiness_sha256: str
    nonce: str
    expires_at: datetime
    durable_store_bound: bool
    anti_replay_is_durable: bool
    caller_constructable_plain_permit: bool

    def __post_init__(self) -> None:
        for field_name in (
            "policy_bundle_sha256",
            "transaction_proof_sha256",
            "signer_readiness_sha256",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_sha256(getattr(self, field_name), field_name),
            )
        if not self.nonce.strip():
            raise PR151ReleasePathError("authorization nonce is required")
        _require_aware_datetime(self.expires_at, "authorization.expires_at")
        _require_bool(self.durable_store_bound, "authorization.durable_store_bound")
        _require_bool(self.anti_replay_is_durable, "authorization.anti_replay_is_durable")
        _require_bool(
            self.caller_constructable_plain_permit,
            "authorization.caller_constructable_plain_permit",
        )


@dataclass(frozen=True, slots=True)
class FinalizedSettlementPolicy:
    get_transaction_finalized_required: bool
    max_supported_transaction_version_zero: bool
    meta_err_must_be_none: bool
    actual_fee_required: bool
    balance_delta_reconciliation_required: bool
    inner_instruction_cpi_required: bool
    simulated_vs_actual_comparison_required: bool
    indeterminate_outcome_freezes_submissions: bool

    def __post_init__(self) -> None:
        for field_name in (
            "get_transaction_finalized_required",
            "max_supported_transaction_version_zero",
            "meta_err_must_be_none",
            "actual_fee_required",
            "balance_delta_reconciliation_required",
            "inner_instruction_cpi_required",
            "simulated_vs_actual_comparison_required",
            "indeterminate_outcome_freezes_submissions",
        ):
            _require_bool(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class JitoCanarySafetyPolicy:
    one_atomic_transaction: bool
    exactly_one_tip: bool
    tip_in_same_transaction: bool
    tip_account_evidence_sha256: str
    bundle_only_reviewed: bool
    standalone_tip_forbidden: bool
    uncle_unbundling_drill_reviewed: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tip_account_evidence_sha256",
            _require_sha256(
                self.tip_account_evidence_sha256,
                "jito.tip_account_evidence_sha256",
            ),
        )
        for field_name in (
            "one_atomic_transaction",
            "exactly_one_tip",
            "tip_in_same_transaction",
            "bundle_only_reviewed",
            "standalone_tip_forbidden",
            "uncle_unbundling_drill_reviewed",
        ):
            _require_bool(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class HermeticReleaseAndSandboxPolicy:
    github_actions_pinned_to_full_sha: bool
    docker_image_pinned_by_digest: bool
    hashed_wheelhouse: bool
    sbom_present: bool
    signed_artifact_provenance: bool
    read_only_root_filesystem: bool
    capabilities_dropped: bool
    no_new_privileges: bool
    seccomp_or_apparmor: bool
    egress_allowlist_enforced: bool
    signer_network_separation: bool

    def __post_init__(self) -> None:
        for field_name in (
            "github_actions_pinned_to_full_sha",
            "docker_image_pinned_by_digest",
            "hashed_wheelhouse",
            "sbom_present",
            "signed_artifact_provenance",
            "read_only_root_filesystem",
            "capabilities_dropped",
            "no_new_privileges",
            "seccomp_or_apparmor",
            "egress_allowlist_enforced",
            "signer_network_separation",
        ):
            _require_bool(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class PR151ReleasePathPackage:
    code_commit: str
    pr150_soak_evidence: PR151EvidenceRef
    isolated_signer: IsolatedSignerBoundary
    authorization: DurableAuthorizationPolicy
    settlement: FinalizedSettlementPolicy
    jito: JitoCanarySafetyPolicy
    release_and_sandbox: HermeticReleaseAndSandboxPolicy
    operator_approvals: Mapping[str, datetime]
    default_live_enabled: bool
    env_can_enable_live: bool
    runtime_command_can_submit: bool
    max_outstanding_submissions: int
    outstanding_submissions: int
    ambiguity_latch_armed: bool
    rollback_to_shadow_available: bool
    manual_kill_switch_armed: bool
    assembled_at: datetime
    assembled_by: str
    schema_version: str = PR151_RELEASE_PATH_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PR151_RELEASE_PATH_SCHEMA:
            raise PR151ReleasePathError("unsupported PR-151 package schema")
        object.__setattr__(self, "code_commit", _require_git_sha(self.code_commit, "code_commit"))
        for field_name in (
            "default_live_enabled",
            "env_can_enable_live",
            "runtime_command_can_submit",
            "ambiguity_latch_armed",
            "rollback_to_shadow_available",
            "manual_kill_switch_armed",
        ):
            _require_bool(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "max_outstanding_submissions",
            _require_non_negative_int(
                self.max_outstanding_submissions,
                "max_outstanding_submissions",
            ),
        )
        object.__setattr__(
            self,
            "outstanding_submissions",
            _require_non_negative_int(
                self.outstanding_submissions,
                "outstanding_submissions",
            ),
        )
        _require_aware_datetime(self.assembled_at, "assembled_at")
        if not self.assembled_by.strip():
            raise PR151ReleasePathError("assembled_by is required")
        for approval in self.operator_approvals.values():
            _require_aware_datetime(approval, "operator_approvals")

    @property
    def package_sha256(self) -> str:
        return _sha256_payload(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class PR151ReleasePathReadiness:
    state: PR151ReleasePathState
    ready_for_manual_release_review: bool
    default_live_enabled: bool
    runtime_live_enabled: bool
    supported_command_can_submit: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    package_sha256: str
    schema_version: str = PR151_RELEASE_PATH_RESULT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_pr151_release_path(
    package: PR151ReleasePathPackage,
) -> PR151ReleasePathReadiness:
    """Evaluate PR-151 evidence while keeping live and submission hard-disabled."""

    blockers: list[str] = []
    warnings: list[str] = []

    _check_evidence(blockers, package.pr150_soak_evidence)
    _check_signer(blockers, package.isolated_signer)
    _check_authorization(blockers, package.authorization, package.assembled_at)
    _check_settlement(blockers, package.settlement)
    _check_jito(blockers, package.jito)
    _check_release_and_sandbox(blockers, package.release_and_sandbox)

    _block(blockers, not package.default_live_enabled, "DEFAULT_LIVE_ENABLED")
    _block(blockers, not package.env_can_enable_live, "ENV_CAN_ENABLE_LIVE")
    _block(
        blockers,
        not package.runtime_command_can_submit,
        "RUNTIME_COMMAND_CAN_SUBMIT_BEFORE_REVIEW",
    )
    _block(blockers, package.max_outstanding_submissions == 1, "OUTSTANDING_LIMIT_NOT_ONE")
    _block(blockers, package.outstanding_submissions == 0, "OUTSTANDING_SUBMISSION_OPEN")
    _block(blockers, package.ambiguity_latch_armed, "AMBIGUITY_LATCH_NOT_ARMED")
    _block(blockers, package.rollback_to_shadow_available, "ROLLBACK_TO_SHADOW_MISSING")
    _block(blockers, package.manual_kill_switch_armed, "MANUAL_KILL_SWITCH_NOT_ARMED")

    approvals = set(package.operator_approvals)
    for required in REQUIRED_RELEASE_SIGNOFFS:
        _block(blockers, required in approvals, f"SIGNOFF_MISSING:{required}")
        approved_at = package.operator_approvals.get(required)
        if approved_at is not None:
            _block(blockers, approved_at <= package.assembled_at, f"SIGNOFF_AFTER_ASSEMBLY:{required}")

    if package.pr150_soak_evidence.name != PR150_SOAK_EVIDENCE_NAME:
        blockers.append("PR150_WRONG_SOAK_EVIDENCE")
    if package.pr150_soak_evidence.human_reviewed and package.pr150_soak_evidence.passed:
        warnings.append("REVIEW_ONLY_GATE_DOES_NOT_ENABLE_LIVE")

    unique_blockers = tuple(dict.fromkeys(blockers))
    ready = not unique_blockers
    return PR151ReleasePathReadiness(
        state=(
            PR151ReleasePathState.READY_FOR_MANUAL_RELEASE_REVIEW
            if ready
            else PR151ReleasePathState.BLOCKED
        ),
        ready_for_manual_release_review=ready,
        default_live_enabled=False,
        runtime_live_enabled=False,
        supported_command_can_submit=False,
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        package_sha256=package.package_sha256,
    )


def _check_evidence(blockers: list[str], evidence: PR151EvidenceRef) -> None:
    _block(blockers, evidence.passed, "PR150_SOAK_EVIDENCE_BLOCKED")
    _block(blockers, evidence.human_reviewed, "PR150_SOAK_EVIDENCE_NOT_REVIEWED")


def _check_signer(blockers: list[str], signer: IsolatedSignerBoundary) -> None:
    _block(blockers, not signer.network_runtime_imports_keypair, "NETWORK_RUNTIME_IMPORTS_KEYPAIR")
    _block(blockers, not signer.signer_has_general_network_access, "SIGNER_HAS_GENERAL_NETWORK")
    _block(blockers, signer.parses_message_independently, "SIGNER_DOES_NOT_PARSE_MESSAGE")
    _block(
        blockers,
        signer.derives_payer_signers_programs_accounts,
        "SIGNER_DOES_NOT_DERIVE_MESSAGE_PARTIES",
    )
    _block(blockers, signer.verifies_policy_and_proof_hashes, "SIGNER_DOES_NOT_VERIFY_PROOFS")
    _block(blockers, signer.verifies_full_wire_transaction_limit, "WIRE_LIMIT_NOT_VERIFIED")
    _block(blockers, signer.returns_signature_only, "SIGNER_RETURNS_MORE_THAN_SIGNATURE")


def _check_authorization(
    blockers: list[str],
    authorization: DurableAuthorizationPolicy,
    assembled_at: datetime,
) -> None:
    _block(blockers, authorization.durable_store_bound, "AUTHORIZATION_NOT_DURABLE_STORE_BOUND")
    _block(blockers, authorization.anti_replay_is_durable, "ANTI_REPLAY_NOT_DURABLE")
    _block(
        blockers,
        not authorization.caller_constructable_plain_permit,
        "CALLER_CONSTRUCTABLE_PLAIN_PERMIT",
    )
    _block(blockers, authorization.expires_at > assembled_at, "AUTHORIZATION_EXPIRED")


def _check_settlement(blockers: list[str], settlement: FinalizedSettlementPolicy) -> None:
    for field_name, reason in (
        ("get_transaction_finalized_required", "FINALIZED_GET_TRANSACTION_NOT_REQUIRED"),
        ("max_supported_transaction_version_zero", "TX_VERSION_ZERO_NOT_REQUIRED"),
        ("meta_err_must_be_none", "META_ERR_SUCCESS_NOT_REQUIRED"),
        ("actual_fee_required", "ACTUAL_FEE_NOT_REQUIRED"),
        ("balance_delta_reconciliation_required", "BALANCE_RECONCILIATION_NOT_REQUIRED"),
        ("inner_instruction_cpi_required", "CPI_EVIDENCE_NOT_REQUIRED"),
        ("simulated_vs_actual_comparison_required", "SIM_ACTUAL_COMPARISON_NOT_REQUIRED"),
        ("indeterminate_outcome_freezes_submissions", "INDETERMINATE_DOES_NOT_FREEZE"),
    ):
        _block(blockers, bool(getattr(settlement, field_name)), reason)


def _check_jito(blockers: list[str], jito: JitoCanarySafetyPolicy) -> None:
    for field_name, reason in (
        ("one_atomic_transaction", "JITO_NOT_ONE_ATOMIC_TRANSACTION"),
        ("exactly_one_tip", "JITO_TIP_NOT_EXACTLY_ONE"),
        ("tip_in_same_transaction", "JITO_TIP_NOT_IN_SAME_TRANSACTION"),
        ("bundle_only_reviewed", "JITO_BUNDLE_ONLY_NOT_REVIEWED"),
        ("standalone_tip_forbidden", "JITO_STANDALONE_TIP_ALLOWED"),
        ("uncle_unbundling_drill_reviewed", "JITO_UNBUNDLING_DRILL_NOT_REVIEWED"),
    ):
        _block(blockers, bool(getattr(jito, field_name)), reason)


def _check_release_and_sandbox(
    blockers: list[str],
    release: HermeticReleaseAndSandboxPolicy,
) -> None:
    for field_name, reason in (
        ("github_actions_pinned_to_full_sha", "ACTIONS_NOT_PINNED_TO_FULL_SHA"),
        ("docker_image_pinned_by_digest", "DOCKER_IMAGE_NOT_PINNED_BY_DIGEST"),
        ("hashed_wheelhouse", "HASHED_WHEELHOUSE_MISSING"),
        ("sbom_present", "SBOM_MISSING"),
        ("signed_artifact_provenance", "SIGNED_PROVENANCE_MISSING"),
        ("read_only_root_filesystem", "ROOT_FILESYSTEM_NOT_READ_ONLY"),
        ("capabilities_dropped", "CAPABILITIES_NOT_DROPPED"),
        ("no_new_privileges", "NO_NEW_PRIVILEGES_MISSING"),
        ("seccomp_or_apparmor", "SECCOMP_OR_APPARMOR_MISSING"),
        ("egress_allowlist_enforced", "EGRESS_ALLOWLIST_MISSING"),
        ("signer_network_separation", "SIGNER_NETWORK_NOT_SEPARATED"),
    ):
        _block(blockers, bool(getattr(release, field_name)), reason)


def _block(blockers: list[str], condition: bool, reason: str) -> None:
    if not condition:
        blockers.append(reason)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _sha256_payload(payload: Any) -> str:
    encoded = json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _require_sha256(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise PR151ReleasePathError(f"{field} must be a non-placeholder sha256")
    return lowered


def _require_git_sha(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _GIT_SHA_RE.fullmatch(lowered) or lowered == "0" * 40:
        raise PR151ReleasePathError(f"{field} must be a non-placeholder git sha")
    return lowered


def _require_bool(value: object, field: str) -> None:
    if not isinstance(value, bool):
        raise PR151ReleasePathError(f"{field} must be bool")


def _require_non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PR151ReleasePathError(f"{field} must be a non-negative integer")
    return value


def _require_aware_datetime(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PR151ReleasePathError(f"{field} must be timezone-aware")
