"""PR-153 immutable policy/admission and attestation gate.

This module is deliberately side-effect free. It does not call providers, RPC,
signers, senders, or live-control code. It evaluates one immutable policy bundle
and proves that an execution role can only be admitted when every required
provider, credential, conformance, attestation, freshness, and operator approval
signal is present.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum, StrEnum
import hashlib
import json
import re
from typing import Any

PR153_POLICY_ADMISSION_SCHEMA = "pr153.policy-admission-truth.v1"
PR153_POLICY_ADMISSION_RESULT_SCHEMA = "pr153.policy-admission-result.v1"
EXECUTABLE_ROLE = "executable"
QUOTE_ONLY_ROLE = "quote-only"
DISCOVERY_ONLY_ROLE = "discovery-only"
DISABLED_ROLE = "disabled"
REQUIRED_EXECUTION_CONDITIONS = (
    "local_contract_active",
    "contract_execution_allowed",
    "drift_free",
    "credentials_present",
    "credentialed_api_conformance",
    "execution_composition_conformance",
    "promotion_evidence",
    "operator_approved",
    "program_attestations_verified",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class PR153PolicyAdmissionError(ValueError):
    """Raised when PR-153 policy/admission evidence is malformed."""


class PR153ReadinessState(StrEnum):
    READY_FOR_POLICY_REVIEW = "ready-for-policy-review"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ProgramAttestation:
    program_id: str
    cluster_genesis_hash: str
    executable_hash: str
    loader: str
    deployment_slot: int
    executable: bool
    upgrade_authority_revoked: bool
    evidence_sha256: str
    stale: bool = False

    def __post_init__(self) -> None:
        _require_text(self.program_id, "program_id")
        _require_text(self.loader, "loader")
        _require_sha256(self.cluster_genesis_hash, "cluster_genesis_hash")
        _require_sha256(self.executable_hash, "executable_hash")
        _require_sha256(self.evidence_sha256, "evidence_sha256")
        _require_non_negative_int(self.deployment_slot, "deployment_slot")
        _require_bool(self.executable, "executable")
        _require_bool(self.upgrade_authority_revoked, "upgrade_authority_revoked")
        _require_bool(self.stale, "stale")

    @property
    def verified(self) -> bool:
        return self.executable and self.upgrade_authority_revoked and not self.stale

    def blockers(self, prefix: str) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.executable:
            blockers.append(f"{prefix}:program-not-executable:{self.program_id}")
        if not self.upgrade_authority_revoked:
            blockers.append(f"{prefix}:upgrade-authority-present:{self.program_id}")
        if self.stale:
            blockers.append(f"{prefix}:program-attestation-stale:{self.program_id}")
        return tuple(blockers)


@dataclass(frozen=True, slots=True)
class ProviderAdmissionEvidence:
    provider: str
    requested_role: str
    local_contract_active: bool
    contract_execution_allowed: bool
    drift_free: bool
    credentials_present: bool
    credentialed_api_conformance: bool
    execution_composition_conformance: bool
    promotion_evidence: bool
    operator_approved: bool
    program_attestations: Sequence[ProgramAttestation]
    required_credentials: tuple[str, ...] = ()
    missing_credentials: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.provider, "provider")
        if self.requested_role not in _supported_roles():
            raise PR153PolicyAdmissionError(
                f"unsupported requested role: {self.requested_role}"
            )
        for field_name in REQUIRED_EXECUTION_CONDITIONS[:-1]:
            _require_bool(getattr(self, field_name), field_name)
        if not self.program_attestations:
            raise PR153PolicyAdmissionError("program_attestations cannot be empty")
        if self.credentials_present and self.missing_credentials:
            raise PR153PolicyAdmissionError(
                "credentials_present cannot coexist with missing_credentials"
            )

    @property
    def program_attestations_verified(self) -> bool:
        return all(attestation.verified for attestation in self.program_attestations)

    @property
    def execution_conditions(self) -> Mapping[str, bool]:
        return {
            "local_contract_active": self.local_contract_active,
            "contract_execution_allowed": self.contract_execution_allowed,
            "drift_free": self.drift_free,
            "credentials_present": self.credentials_present,
            "credentialed_api_conformance": self.credentialed_api_conformance,
            "execution_composition_conformance": self.execution_composition_conformance,
            "promotion_evidence": self.promotion_evidence,
            "operator_approved": self.operator_approved,
            "program_attestations_verified": self.program_attestations_verified,
        }

    def execution_blockers(self) -> tuple[str, ...]:
        blockers = [
            f"{self.provider}:{name}"
            for name, ok in self.execution_conditions.items()
            if not ok
        ]
        for attestation in self.program_attestations:
            blockers.extend(attestation.blockers(self.provider))
        for credential in self.missing_credentials:
            blockers.append(f"{self.provider}:missing-credential:{credential}")
        return _dedupe(blockers)


@dataclass(frozen=True, slots=True)
class ImmutablePolicyBundle:
    policy_version: str
    build_commit: str
    cluster_genesis_hash: str
    providers: Sequence[ProviderAdmissionEvidence]
    operator_approval_id: str
    runtime_truth_sha256: str
    schema_version: str = PR153_POLICY_ADMISSION_SCHEMA
    live_enabled: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != PR153_POLICY_ADMISSION_SCHEMA:
            raise PR153PolicyAdmissionError("unsupported PR-153 policy schema")
        _require_text(self.policy_version, "policy_version")
        _require_git_sha(self.build_commit, "build_commit")
        _require_sha256(self.cluster_genesis_hash, "cluster_genesis_hash")
        _require_sha256(self.runtime_truth_sha256, "runtime_truth_sha256")
        _require_text(self.operator_approval_id, "operator_approval_id")
        _require_bool(self.live_enabled, "live_enabled")
        if self.live_enabled:
            raise PR153PolicyAdmissionError("PR-153 policy bundle cannot enable live")
        if not self.providers:
            raise PR153PolicyAdmissionError("policy bundle requires at least one provider")
        provider_names = [provider.provider for provider in self.providers]
        if len(provider_names) != len(set(provider_names)):
            raise PR153PolicyAdmissionError("provider names must be unique")
        for provider in self.providers:
            for attestation in provider.program_attestations:
                if attestation.cluster_genesis_hash != self.cluster_genesis_hash:
                    raise PR153PolicyAdmissionError(
                        "provider attestation cluster does not match policy bundle"
                    )

    @property
    def bundle_sha256(self) -> str:
        return _sha256_payload(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = _jsonable(self)
        if include_hash:
            payload["policy_bundle_sha256"] = self.bundle_sha256
        return payload


@dataclass(frozen=True, slots=True)
class ProviderAdmissionDecision:
    provider: str
    requested_role: str
    admitted_role: str
    executable: bool
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class PolicyAdmissionResult:
    state: PR153ReadinessState
    ready_for_policy_review: bool
    runtime_live_enabled: bool
    supported_command_can_submit: bool
    policy_bundle_sha256: str
    provider_decisions: tuple[ProviderAdmissionDecision, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    schema_version: str = PR153_POLICY_ADMISSION_RESULT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_pr153_policy_admission(
    bundle: ImmutablePolicyBundle,
) -> PolicyAdmissionResult:
    decisions: list[ProviderAdmissionDecision] = []
    blockers: list[str] = []
    warnings: list[str] = []

    for provider in bundle.providers:
        provider_blockers = provider.execution_blockers()
        admitted_role = _admitted_role(provider, provider_blockers)
        executable = admitted_role == EXECUTABLE_ROLE
        if provider.requested_role == EXECUTABLE_ROLE and provider_blockers:
            blockers.extend(provider_blockers)
        if provider.requested_role != EXECUTABLE_ROLE and provider_blockers:
            warnings.extend(provider_blockers)
        decisions.append(
            ProviderAdmissionDecision(
                provider=provider.provider,
                requested_role=provider.requested_role,
                admitted_role=admitted_role,
                executable=executable,
                blockers=provider_blockers,
            )
        )

    if not any(decision.executable for decision in decisions):
        blockers.append("no-provider-admitted-for-execution")

    unique_blockers = _dedupe(blockers)
    ready = not unique_blockers
    return PolicyAdmissionResult(
        state=(
            PR153ReadinessState.READY_FOR_POLICY_REVIEW
            if ready
            else PR153ReadinessState.BLOCKED
        ),
        ready_for_policy_review=ready,
        runtime_live_enabled=False,
        supported_command_can_submit=False,
        policy_bundle_sha256=bundle.bundle_sha256,
        provider_decisions=tuple(decisions),
        blockers=unique_blockers,
        warnings=_dedupe(warnings),
    )


def assert_no_false_provider_promotion(result: PolicyAdmissionResult) -> None:
    for decision in result.provider_decisions:
        if decision.executable and decision.blockers:
            raise PR153PolicyAdmissionError(
                f"{decision.provider}: executable role admitted with blockers"
            )
    if result.runtime_live_enabled or result.supported_command_can_submit:
        raise PR153PolicyAdmissionError("PR-153 result cannot enable live submission")


def _admitted_role(
    provider: ProviderAdmissionEvidence,
    provider_blockers: tuple[str, ...],
) -> str:
    if provider.requested_role != EXECUTABLE_ROLE:
        return provider.requested_role
    if provider_blockers:
        return DISABLED_ROLE
    return EXECUTABLE_ROLE


def _supported_roles() -> frozenset[str]:
    return frozenset(
        {EXECUTABLE_ROLE, QUOTE_ONLY_ROLE, DISCOVERY_ONLY_ROLE, DISABLED_ROLE}
    )


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item) for item in value]
    return value


def _stable_json(payload: Any) -> str:
    return json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _require_text(value: str, field: str) -> str:
    text = str(value).strip()
    if not text:
        raise PR153PolicyAdmissionError(f"{field} is required")
    return text


def _require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise PR153PolicyAdmissionError(f"{field} must be bool")
    return value


def _require_non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PR153PolicyAdmissionError(f"{field} must be a non-negative int")
    return value


def _require_sha256(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise PR153PolicyAdmissionError(f"{field} must be a non-placeholder sha256")
    return lowered


def _require_git_sha(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _GIT_SHA_RE.fullmatch(lowered) or lowered == "0" * 40:
        raise PR153PolicyAdmissionError(f"{field} must be a non-placeholder git sha")
    return lowered


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))
