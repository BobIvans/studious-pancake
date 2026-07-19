from __future__ import annotations

import hashlib

from .models import (
    AssessmentValidity,
    CandidateStatus,
    IndexedPosition,
    LendingProtocol,
    LendingSnapshot,
    LiquidationCandidate,
    LiquidationConstraints,
    Pubkey,
    ReasonCode,
    RiskAssessment,
    RiskRequirement,
)


def candidate_id(
    protocol: LendingProtocol,
    deployment_id: str,
    account: Pubkey,
    snapshot_hash: str,
    risk_hash: str,
) -> str:
    payload = "|".join((protocol.value, deployment_id, account, snapshot_hash, risk_hash))
    return hashlib.sha256(payload.encode()).hexdigest()


def classify(
    protocol: LendingProtocol,
    deployment_id: str,
    snapshot: LendingSnapshot,
    assessment: RiskAssessment,
    positions: tuple[IndexedPosition, ...],
    constraints: LiquidationConstraints,
    reason: ReasonCode | None = None,
) -> LiquidationCandidate:
    if assessment.validity is AssessmentValidity.UNKNOWN:
        status = CandidateStatus.UNKNOWN
    elif assessment.validity is AssessmentValidity.EXCLUDED or reason is not None:
        status = CandidateStatus.EXCLUDED
    elif assessment.requirement is RiskRequirement.MAINTENANCE and assessment.health < 0:
        status = CandidateStatus.POTENTIALLY_LIQUIDATABLE
    else:
        status = CandidateStatus.WATCH
    cid = candidate_id(
        protocol,
        deployment_id,
        assessment.account,
        snapshot.account_set_hash,
        assessment.evidence.risk_config_hash,
    )
    return LiquidationCandidate(
        cid,
        protocol,
        assessment.account,
        snapshot.read_slot,
        assessment,
        positions,
        constraints,
        status,
        reason,
    )
