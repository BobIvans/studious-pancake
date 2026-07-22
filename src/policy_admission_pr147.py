"""PR-147 immutable policy bundle and provider admission truth.

This module is intentionally side-effect free. It does not read environment
variables, call provider/RPC endpoints, sign, submit, or mutate active runtime
state. It defines deterministic policy/admission contracts for later runtime
wiring.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping

PR147_POLICY_SCHEMA = "pr147.immutable-policy-admission.v1"
POLICY_BUNDLE_DOMAIN = "flashloan-bot/pr147-policy-bundle"
PROVIDER_EVIDENCE_DOMAIN = "flashloan-bot/pr147-provider-evidence"
ADMISSION_DECISION_DOMAIN = "flashloan-bot/pr147-provider-admission"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PolicyAdmissionError(ValueError):
    """Raised when policy/admission evidence describes an impossible state."""


class RequestedProviderRole(StrEnum):
    DISABLED = "disabled"
    DISCOVERY_ONLY = "discovery-only"
    EXECUTABLE = "executable"


class AdmittedProviderRole(StrEnum):
    DISABLED = "disabled"
    DISCOVERY_ONLY = "discovery-only"
    EXECUTABLE = "executable"


@dataclass(frozen=True, slots=True)
class HashReference:
    """Domain-qualified immutable evidence reference."""

    domain: str
    digest: str

    def __post_init__(self) -> None:
        _require_name(self.domain, "hash domain")
        _require_sha256(self.digest, "hash digest")


@dataclass(frozen=True, slots=True)
class ImmutablePolicyBundle:
    """One startup/runtime policy identity for admission decisions."""

    cluster_genesis: str
    runtime_config_hash: str
    secret_locator_hash: str
    provider_contracts_hash: str
    credential_availability_hash: str
    program_attestations_hash: str
    asset_mint_registry_hash: str
    freshness_policy_hash: str
    build_release_hash: str
    operator_approval_hash: str
    schema_version: str = PR147_POLICY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PR147_POLICY_SCHEMA:
            raise PolicyAdmissionError("unsupported policy bundle schema")
        _require_name(self.cluster_genesis, "cluster genesis")
        for field_name in (
            "runtime_config_hash",
            "secret_locator_hash",
            "provider_contracts_hash",
            "credential_availability_hash",
            "program_attestations_hash",
            "asset_mint_registry_hash",
            "freshness_policy_hash",
            "build_release_hash",
            "operator_approval_hash",
        ):
            _require_sha256(str(getattr(self, field_name)), field_name)

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "cluster_genesis": self.cluster_genesis,
            "runtime_config_hash": self.runtime_config_hash,
            "secret_locator_hash": self.secret_locator_hash,
            "provider_contracts_hash": self.provider_contracts_hash,
            "credential_availability_hash": self.credential_availability_hash,
            "program_attestations_hash": self.program_attestations_hash,
            "asset_mint_registry_hash": self.asset_mint_registry_hash,
            "freshness_policy_hash": self.freshness_policy_hash,
            "build_release_hash": self.build_release_hash,
            "operator_approval_hash": self.operator_approval_hash,
        }

    @property
    def bundle_hash(self) -> str:
        return domain_hash(POLICY_BUNDLE_DOMAIN, self.payload)


@dataclass(frozen=True, slots=True)
class ProgramAttestation:
    """Current on-chain deployment identity used by provider/runtime policy."""

    program_id: str
    cluster_genesis: str
    executable: bool
    deployment_slot: int
    programdata_hash: str
    upgrade_authority: str | None
    evidence_hash: str
    stale: bool = False

    def __post_init__(self) -> None:
        _require_name(self.program_id, "program_id")
        _require_name(self.cluster_genesis, "cluster_genesis")
        if self.deployment_slot < 0:
            raise PolicyAdmissionError("deployment_slot cannot be negative")
        _require_sha256(self.programdata_hash, "programdata_hash")
        _require_sha256(self.evidence_hash, "program evidence_hash")

    @property
    def current(self) -> bool:
        return self.executable and not self.stale


@dataclass(frozen=True, slots=True)
class MintAttestation:
    """Tradability decision for one asset/mint identity."""

    mint: str
    owner_program_id: str
    supported: bool
    evidence_hash: str
    extensions_hash: str | None = None
    tradable: bool = False

    def __post_init__(self) -> None:
        _require_name(self.mint, "mint")
        _require_name(self.owner_program_id, "owner_program_id")
        _require_sha256(self.evidence_hash, "mint evidence_hash")
        if self.extensions_hash is not None:
            _require_sha256(self.extensions_hash, "mint extensions_hash")
        if self.tradable and not self.supported:
            raise PolicyAdmissionError("unsupported mint cannot be tradable")


@dataclass(frozen=True, slots=True)
class ProviderPolicyEvidence:
    """Immutable, already-collected provider evidence for one startup generation."""

    provider: str
    requested_role: RequestedProviderRole
    contract_id: str
    local_contract_active: bool
    contract_execution_allowed: bool
    credentials_present: bool
    credentialed_api_conformance: bool
    execution_composition_conformance: bool
    promotion_evidence: bool
    current_policy_approval: bool
    no_drift: bool
    evidence_age_slots: int
    max_evidence_age_slots: int
    program_attestations: tuple[ProgramAttestation, ...] = ()
    requires_on_chain_attestation: bool = False

    def __post_init__(self) -> None:
        _require_name(self.provider, "provider")
        _require_name(self.contract_id, "contract_id")
        if self.evidence_age_slots < 0 or self.max_evidence_age_slots < 0:
            raise PolicyAdmissionError("evidence ages cannot be negative")

    @property
    def evidence_hash(self) -> str:
        return domain_hash(
            PROVIDER_EVIDENCE_DOMAIN,
            {
                "provider": self.provider,
                "requested_role": self.requested_role.value,
                "contract_id": self.contract_id,
                "local_contract_active": self.local_contract_active,
                "contract_execution_allowed": self.contract_execution_allowed,
                "credentials_present": self.credentials_present,
                "credentialed_api_conformance": self.credentialed_api_conformance,
                "execution_composition_conformance": (
                    self.execution_composition_conformance
                ),
                "promotion_evidence": self.promotion_evidence,
                "current_policy_approval": self.current_policy_approval,
                "no_drift": self.no_drift,
                "evidence_age_slots": self.evidence_age_slots,
                "max_evidence_age_slots": self.max_evidence_age_slots,
                "requires_on_chain_attestation": self.requires_on_chain_attestation,
                "program_attestations": [
                    {
                        "program_id": item.program_id,
                        "cluster_genesis": item.cluster_genesis,
                        "executable": item.executable,
                        "deployment_slot": item.deployment_slot,
                        "programdata_hash": item.programdata_hash,
                        "upgrade_authority": item.upgrade_authority,
                        "evidence_hash": item.evidence_hash,
                        "stale": item.stale,
                    }
                    for item in self.program_attestations
                ],
            },
        )


@dataclass(frozen=True, slots=True)
class ProviderAdmissionDecision:
    """One decisive runtime role derived from one policy bundle and evidence set."""

    provider: str
    requested_role: RequestedProviderRole
    admitted_role: AdmittedProviderRole
    execution_allowed: bool
    request_ready: bool
    startup_ready: bool
    reasons: tuple[str, ...]
    policy_bundle_hash: str
    provider_evidence_hash: str

    @property
    def decision_hash(self) -> str:
        return domain_hash(
            ADMISSION_DECISION_DOMAIN,
            {
                "provider": self.provider,
                "requested_role": self.requested_role.value,
                "admitted_role": self.admitted_role.value,
                "execution_allowed": self.execution_allowed,
                "request_ready": self.request_ready,
                "startup_ready": self.startup_ready,
                "reasons": list(self.reasons),
                "policy_bundle_hash": self.policy_bundle_hash,
                "provider_evidence_hash": self.provider_evidence_hash,
            },
        )


@dataclass(frozen=True, slots=True)
class PolicyRuntimeTruth:
    """Small PR-147 truth object for admission and asset/mint impossibility checks."""

    policy_bundle: ImmutablePolicyBundle
    provider_decisions: Mapping[str, ProviderAdmissionDecision]
    mint_attestations: Mapping[str, MintAttestation]

    def __post_init__(self) -> None:
        provider_map = MappingProxyType(dict(self.provider_decisions))
        mint_map = MappingProxyType(dict(self.mint_attestations))
        object.__setattr__(self, "provider_decisions", provider_map)
        object.__setattr__(self, "mint_attestations", mint_map)
        for name, decision in provider_map.items():
            if name != decision.provider:
                raise PolicyAdmissionError("provider decision key mismatch")
            if (
                decision.admitted_role is AdmittedProviderRole.EXECUTABLE
                and not decision.execution_allowed
            ):
                raise PolicyAdmissionError(
                    f"{name}: execution_allowed=false + executable is impossible"
                )
            if decision.startup_ready and not decision.request_ready:
                raise PolicyAdmissionError(
                    f"{name}: startup_ready=true while request_ready=false"
                )
        for mint, attestation in mint_map.items():
            if mint != attestation.mint:
                raise PolicyAdmissionError("mint attestation key mismatch")

    @property
    def executable_providers(self) -> tuple[str, ...]:
        return tuple(
            name
            for name, decision in self.provider_decisions.items()
            if decision.admitted_role is AdmittedProviderRole.EXECUTABLE
        )

    @property
    def tradable_mints(self) -> tuple[str, ...]:
        return tuple(
            mint
            for mint, attestation in self.mint_attestations.items()
            if attestation.tradable
        )

    @property
    def paper_ready(self) -> bool:
        return bool(self.executable_providers) and bool(self.tradable_mints)

    @property
    def blocking_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        for decision in self.provider_decisions.values():
            reasons.extend(f"{decision.provider}:{reason}" for reason in decision.reasons)
        if not self.executable_providers:
            reasons.append("no-executable-provider")
        if not self.tradable_mints:
            reasons.append("no-tradable-mint")
        return tuple(dict.fromkeys(reasons))


def evaluate_provider_admission(
    policy_bundle: ImmutablePolicyBundle,
    evidence: ProviderPolicyEvidence,
) -> ProviderAdmissionDecision:
    """Assign a runtime role only from decisive immutable evidence."""

    reasons = _provider_blocking_reasons(policy_bundle, evidence)
    executable_allowed = (
        evidence.requested_role is RequestedProviderRole.EXECUTABLE
        and not reasons
    )
    if executable_allowed:
        admitted_role = AdmittedProviderRole.EXECUTABLE
    elif (
        evidence.requested_role is not RequestedProviderRole.DISABLED
        and evidence.local_contract_active
        and evidence.no_drift
        and evidence.credentials_present
    ):
        admitted_role = AdmittedProviderRole.DISCOVERY_ONLY
    else:
        admitted_role = AdmittedProviderRole.DISABLED

    request_ready = admitted_role is not AdmittedProviderRole.DISABLED
    startup_ready = request_ready and not reasons
    return ProviderAdmissionDecision(
        provider=evidence.provider,
        requested_role=evidence.requested_role,
        admitted_role=admitted_role,
        execution_allowed=executable_allowed,
        request_ready=request_ready,
        startup_ready=startup_ready,
        reasons=tuple(reasons),
        policy_bundle_hash=policy_bundle.bundle_hash,
        provider_evidence_hash=evidence.evidence_hash,
    )


def require_domain(ref: HashReference, expected_domain: str) -> None:
    if ref.domain != expected_domain:
        raise PolicyAdmissionError(
            f"hash domain mismatch: expected {expected_domain}, got {ref.domain}"
        )


def domain_hash(domain: str, payload: object) -> str:
    _require_name(domain, "hash domain")
    raw = json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(domain.encode("utf-8") + b"\0" + raw).hexdigest()


def _jsonable(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _provider_blocking_reasons(
    policy_bundle: ImmutablePolicyBundle,
    evidence: ProviderPolicyEvidence,
) -> list[str]:
    reasons: list[str] = []
    if evidence.requested_role is RequestedProviderRole.DISABLED:
        reasons.append("provider-disabled-by-policy")
    if evidence.local_contract_active is False:
        reasons.append("local-contract-inactive")
    if evidence.no_drift is False:
        reasons.append("contract-or-evidence-drift")
    if evidence.credentials_present is False:
        reasons.append("missing-credentials")
    if evidence.contract_execution_allowed is False:
        reasons.append("contract-execution-denied")
    if evidence.credentialed_api_conformance is False:
        reasons.append("credentialed-api-conformance-missing")
    if evidence.execution_composition_conformance is False:
        reasons.append("execution-composition-conformance-missing")
    if evidence.promotion_evidence is False:
        reasons.append("promotion-evidence-missing")
    if evidence.current_policy_approval is False:
        reasons.append("policy-approval-missing")
    if evidence.evidence_age_slots > evidence.max_evidence_age_slots:
        reasons.append("evidence-stale")
    if evidence.requires_on_chain_attestation and not evidence.program_attestations:
        reasons.append("program-attestation-missing")
    for attestation in evidence.program_attestations:
        if attestation.cluster_genesis != policy_bundle.cluster_genesis:
            reasons.append(f"program:{attestation.program_id}:wrong-genesis")
        if not attestation.current:
            reasons.append(f"program:{attestation.program_id}:stale-or-not-executable")
    return list(dict.fromkeys(reasons))


def _require_sha256(value: str, field_name: str) -> None:
    if not _SHA256_RE.fullmatch(value):
        raise PolicyAdmissionError(f"{field_name} must be a lowercase SHA-256 hex")


def _require_name(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise PolicyAdmissionError(f"{field_name} must be non-empty")


__all__ = [
    "ADMISSION_DECISION_DOMAIN",
    "POLICY_BUNDLE_DOMAIN",
    "PROVIDER_EVIDENCE_DOMAIN",
    "AdmittedProviderRole",
    "HashReference",
    "ImmutablePolicyBundle",
    "MintAttestation",
    "PolicyAdmissionError",
    "PolicyRuntimeTruth",
    "ProgramAttestation",
    "ProviderAdmissionDecision",
    "ProviderPolicyEvidence",
    "RequestedProviderRole",
    "domain_hash",
    "evaluate_provider_admission",
    "require_domain",
]
