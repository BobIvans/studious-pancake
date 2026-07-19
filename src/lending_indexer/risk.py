from __future__ import annotations

from fractions import Fraction

from .models import AssessmentValidity, OracleStatus, Pubkey, RiskAssessment, RiskEvidence, RiskRequirement


def health_factor(assets: Fraction, liabilities: Fraction) -> Fraction | None:
    return None if liabilities == 0 else assets / liabilities


def assess_maintenance(
    account: Pubkey,
    weighted_assets: Fraction,
    weighted_liabilities: Fraction,
    oracle_status: OracleStatus,
    evidence: RiskEvidence,
) -> RiskAssessment:
    validity = AssessmentValidity.VALID if oracle_status is OracleStatus.VALID else AssessmentValidity.EXCLUDED
    return RiskAssessment(
        account,
        RiskRequirement.MAINTENANCE,
        weighted_assets,
        weighted_liabilities,
        weighted_assets - weighted_liabilities,
        health_factor(weighted_assets, weighted_liabilities),
        oracle_status,
        validity,
        evidence,
    )
