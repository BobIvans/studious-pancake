"""PR-051 advisory-only guardrail for AI decision intelligence.

The functions in this module are deliberately side-effect free. They do not
size trades, mutate allowlists, open permits, call senders, or change live
policy. A model can only attach a shadow/advisory explanation to a candidate
that was already processed by deterministic policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .contracts import ModelStatus, RankingRecommendation, RecommendedBand

ADVISORY_POLICY_VERSION = "pr051.advisory-only-envelope.v1"
FORBIDDEN_AI_CONTROL_SURFACES = (
    "sizing",
    "position_size",
    "min_profit",
    "allowlist",
    "permit",
    "sender",
    "submit",
    "kill_switch",
    "live_policy",
    "live_enabled",
    "risk_limit",
)


@dataclass(frozen=True, slots=True)
class DeterministicCandidateDecision:
    """Authoritative non-AI decision that has already run for a candidate."""

    candidate_id: str
    deterministic_allowed: bool
    baseline_priority: int
    reject_reasons: tuple[str, ...] = field(default_factory=tuple)
    deterministic_policy_hash: str | None = None


@dataclass(frozen=True, slots=True)
class AdvisoryDecisionEnvelope:
    """Safe envelope that can be logged or compared in shadow mode only."""

    candidate_id: str
    policy_version: str
    deterministic_allowed: bool
    final_allowed: bool
    baseline_priority: int
    advisory_probability: float | None
    advisory_band: RecommendedBand
    advisory_reasons: tuple[str, ...]
    model_status: ModelStatus
    artifact_checksum: str | None
    guardrail_reasons: tuple[str, ...]
    deterministic_policy_hash: str | None = None
    advisory_only: bool = True


def _walk_forbidden_keys(obj: Any, path: tuple[str, ...] = ()) -> tuple[str, ...]:
    findings: list[str] = []
    if isinstance(obj, Mapping):
        for raw_key, value in obj.items():
            key = str(raw_key)
            lowered = key.lower()
            next_path = path + (key,)
            if any(token in lowered for token in FORBIDDEN_AI_CONTROL_SURFACES):
                findings.append(".".join(next_path))
            findings.extend(_walk_forbidden_keys(value, next_path))
    elif isinstance(obj, (list, tuple)):
        for index, value in enumerate(obj):
            findings.extend(_walk_forbidden_keys(value, path + (str(index),)))
    return tuple(findings)


def assert_no_ai_control_surface(payload: Mapping[str, Any]) -> None:
    """Reject AI payloads that try to touch deterministic control surfaces."""

    findings = sorted(set(_walk_forbidden_keys(payload)))
    if findings:
        raise ValueError(f"AI advisory payload references forbidden controls: {findings}")


def apply_advisory_guard(
    deterministic: DeterministicCandidateDecision,
    recommendation: RankingRecommendation,
) -> AdvisoryDecisionEnvelope:
    """Merge deterministic policy with an AI recommendation without promotion.

    ``final_allowed`` is always copied from deterministic policy. Even a strong
    model ``PRIORITIZE`` recommendation cannot turn a rejected candidate into an
    accepted candidate.
    """

    guardrails: list[str] = []
    if not deterministic.deterministic_allowed:
        guardrails.append("DETERMINISTIC_REJECT_AUTHORITATIVE")
        if recommendation.recommended_band is RecommendedBand.PRIORITIZE:
            guardrails.append("AI_PRIORITIZE_IGNORED_FOR_REJECTED_CANDIDATE")
    if recommendation.baseline_priority != deterministic.baseline_priority:
        guardrails.append("BASELINE_PRIORITY_FROM_DETERMINISTIC_POLICY_PRESERVED")

    return AdvisoryDecisionEnvelope(
        candidate_id=deterministic.candidate_id,
        policy_version=ADVISORY_POLICY_VERSION,
        deterministic_allowed=deterministic.deterministic_allowed,
        final_allowed=deterministic.deterministic_allowed,
        baseline_priority=deterministic.baseline_priority,
        advisory_probability=recommendation.probability,
        advisory_band=recommendation.recommended_band,
        advisory_reasons=tuple(recommendation.explanations),
        model_status=recommendation.model_status,
        artifact_checksum=recommendation.artifact_checksum,
        guardrail_reasons=tuple(guardrails),
        deterministic_policy_hash=deterministic.deterministic_policy_hash,
    )
