"""RND-04: evidence-bound promotion decisions for research prototypes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum

from .common import ResearchOutcome, hash_json, require_id, require_sha256


class PromotionDecisionKind(StrEnum):
    SCOPED_INTEGRATION_REVIEW = "scoped-integration-review"
    CONTINUE_RESEARCH = "continue-research"
    REJECTED_WITH_EVIDENCE = "rejected-with-evidence"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ResearchPromotionDecision:
    experiment_id: str
    benchmark_sha256: str
    baseline_sha256: str
    outcome: ResearchOutcome
    reproducible: bool
    end_to_end_cost_measured: bool
    safety_reviewed: bool
    integration_tests_passed: bool
    resource_policy_satisfied: bool
    requested_risk_increase: bool
    decision: PromotionDecisionKind
    blockers: tuple[str, ...]
    execution_authority_granted: bool = False
    production_ready: bool = False

    def __post_init__(self) -> None:
        require_id(self.experiment_id, "experiment_id")
        require_sha256(self.benchmark_sha256, "benchmark_sha256")
        require_sha256(self.baseline_sha256, "baseline_sha256")
        if self.execution_authority_granted or self.production_ready:
            raise ValueError("research promotion cannot grant execution/production authority")
        if self.decision is PromotionDecisionKind.SCOPED_INTEGRATION_REVIEW and self.blockers:
            raise ValueError("scoped integration review cannot retain blockers")

    @property
    def decision_sha256(self) -> str:
        return hash_json("agg14/research-promotion-decision/v1", asdict(self))


def evaluate_research_promotion(
    *,
    experiment_id: str,
    benchmark_sha256: str,
    baseline_sha256: str,
    outcome: ResearchOutcome,
    reproducible: bool,
    end_to_end_cost_measured: bool,
    safety_reviewed: bool,
    integration_tests_passed: bool,
    resource_policy_satisfied: bool,
    requested_risk_increase: bool,
) -> ResearchPromotionDecision:
    blockers: list[str] = []
    if not reproducible:
        blockers.append("RESEARCH_RESULT_NOT_REPRODUCIBLE")
    if not end_to_end_cost_measured:
        blockers.append("RESEARCH_END_TO_END_COST_UNMEASURED")
    if not safety_reviewed:
        blockers.append("RESEARCH_SAFETY_REVIEW_MISSING")
    if not integration_tests_passed:
        blockers.append("RESEARCH_INTEGRATION_TESTS_MISSING")
    if not resource_policy_satisfied:
        blockers.append("RESEARCH_RESOURCE_POLICY_NOT_SATISFIED")
    if requested_risk_increase:
        blockers.append("RESEARCH_SELF_APPROVED_RISK_INCREASE_DENIED")

    if outcome is ResearchOutcome.NEGATIVE and reproducible:
        decision = PromotionDecisionKind.REJECTED_WITH_EVIDENCE
    elif outcome is ResearchOutcome.INCONCLUSIVE:
        decision = PromotionDecisionKind.CONTINUE_RESEARCH
    elif outcome is ResearchOutcome.BLOCKED:
        decision = PromotionDecisionKind.BLOCKED
    elif blockers:
        decision = PromotionDecisionKind.BLOCKED
    else:
        decision = PromotionDecisionKind.SCOPED_INTEGRATION_REVIEW

    return ResearchPromotionDecision(
        experiment_id=experiment_id,
        benchmark_sha256=benchmark_sha256,
        baseline_sha256=baseline_sha256,
        outcome=outcome,
        reproducible=reproducible,
        end_to_end_cost_measured=end_to_end_cost_measured,
        safety_reviewed=safety_reviewed,
        integration_tests_passed=integration_tests_passed,
        resource_policy_satisfied=resource_policy_satisfied,
        requested_risk_increase=requested_risk_increase,
        decision=decision,
        blockers=tuple(blockers),
    )


__all__ = [
    "PromotionDecisionKind",
    "ResearchPromotionDecision",
    "evaluate_research_promotion",
]
