"""AGG-11 CHAIN-06: per-chain qualification and evidence isolation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json

from .core import (
    CapabilityStatus,
    ChainCapabilityRegistry,
    ChainDialect,
    DeploymentRef,
    MultiChainError,
)


class ChainQualificationStatus(StrEnum):
    BLOCKED = "blocked"
    IMPLEMENTED_OFFLINE = "implemented_offline"
    EXTERNALLY_QUALIFIED = "externally_qualified_for_profile"


@dataclass(frozen=True, slots=True)
class ChainEvidence:
    chain_key: str
    profile_id: str
    dialect: ChainDialect
    state_proof: bool
    math_proof: bool
    simulation_proof: bool
    economics_proof: bool
    permission_proof: bool
    gas_or_fee_proof: bool
    finality_proof: bool
    operational_proof: bool = False
    deployment_digests: tuple[str, ...] = ()

    @property
    def offline_complete(self) -> bool:
        return all(
            (
                self.state_proof,
                self.math_proof,
                self.simulation_proof,
                self.economics_proof,
                self.permission_proof,
                self.gas_or_fee_proof,
                self.finality_proof,
            )
        )


@dataclass(frozen=True, slots=True)
class ChainQualificationVerdict:
    chain_key: str
    profile_id: str
    dialect: ChainDialect
    status: ChainQualificationStatus
    blockers: tuple[str, ...]
    evidence: ChainEvidence
    live_enabled: bool = False

    @property
    def externally_qualified(self) -> bool:
        return self.status is ChainQualificationStatus.EXTERNALLY_QUALIFIED


def deployment_evidence_digest(deployment: DeploymentRef) -> str:
    """Content-bind deployment identity without relying on a mutable registry key."""

    payload = {
        "protocol": deployment.protocol,
        "chain_key": deployment.chain_key,
        "deployment_id": deployment.deployment_id,
        "version": deployment.version,
        "interface_digest": deployment.interface_digest,
        "artifact_digest": deployment.artifact_digest,
        "generation": deployment.generation,
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def require_single_chain_atomic_scope(chain_keys: tuple[str, ...]) -> str:
    unique = tuple(dict.fromkeys(chain_keys))
    if len(unique) != 1:
        raise MultiChainError(
            "CROSS_CHAIN_ATOMICITY_FORBIDDEN",
            "AGG-11 atomic plans must stay inside one chain dialect",
            stage="planning",
        )
    return unique[0]


def require_evidence_scope(
    evidence: ChainEvidence,
    *,
    chain_key: str,
    profile_id: str,
    deployment_digests: tuple[str, ...],
) -> None:
    if evidence.chain_key != chain_key:
        raise MultiChainError(
            "EVIDENCE_CHAIN_MISMATCH",
            "chain evidence cannot qualify another network",
        )
    if evidence.profile_id != profile_id:
        raise MultiChainError(
            "EVIDENCE_PROFILE_MISMATCH",
            "profile evidence cannot qualify another profile",
        )
    if tuple(evidence.deployment_digests) != tuple(deployment_digests):
        raise MultiChainError(
            "EVIDENCE_DEPLOYMENT_MISMATCH",
            "deployment evidence generation differs",
        )


def qualify_chain(
    *,
    registry: ChainCapabilityRegistry,
    chain_key: str,
    profile_id: str,
    capability_ids: tuple[str, ...],
    evidence: ChainEvidence,
    require_operational: bool = False,
) -> ChainQualificationVerdict:
    chain = registry.chain(chain_key)
    if chain.dialect is ChainDialect.SOLANA:
        raise MultiChainError(
            "SOLANA_OWNER_UNCHANGED",
            "existing Solana runtime owns Solana qualification",
        )
    if evidence.chain_key != chain_key or evidence.profile_id != profile_id:
        raise MultiChainError(
            "QUALIFICATION_SCOPE_MISMATCH",
            "evidence scope differs from requested profile",
        )
    if evidence.dialect is not chain.dialect:
        raise MultiChainError(
            "QUALIFICATION_DIALECT_MISMATCH",
            "evidence uses another chain dialect",
        )
    blockers = list(chain.blockers)
    deployments: list[str] = []
    for capability_id in capability_ids:
        capability = registry.capability(capability_id)
        if capability.chain_key != chain_key:
            blockers.append(f"{capability_id}:CHAIN_MISMATCH")
            continue
        if capability.status in {
            CapabilityStatus.UNAVAILABLE,
            CapabilityStatus.REVOKED,
        }:
            blockers.append(f"{capability_id}:STATUS_{capability.status.value}")
        blockers.extend(
            f"{capability_id}:{blocker}"
            for blocker in capability.blockers
        )
        if capability.deployment is not None:
            deployments.append(deployment_evidence_digest(capability.deployment))
    if not evidence.offline_complete:
        blockers.append("OFFLINE_EVIDENCE_INCOMPLETE")
    if require_operational and not evidence.operational_proof:
        blockers.append("OPERATIONAL_EVIDENCE_MISSING")
    if tuple(evidence.deployment_digests) != tuple(deployments):
        blockers.append("DEPLOYMENT_EVIDENCE_GENERATION_MISMATCH")
    unique = tuple(dict.fromkeys(blockers))
    if unique:
        status = ChainQualificationStatus.BLOCKED
    elif require_operational:
        status = ChainQualificationStatus.EXTERNALLY_QUALIFIED
    else:
        status = ChainQualificationStatus.IMPLEMENTED_OFFLINE
    return ChainQualificationVerdict(
        chain_key=chain_key,
        profile_id=profile_id,
        dialect=chain.dialect,
        status=status,
        blockers=unique,
        evidence=evidence,
        live_enabled=False,
    )
