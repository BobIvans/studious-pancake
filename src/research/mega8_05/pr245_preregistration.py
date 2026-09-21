"""PR-245 / EXPERIMENT-01: immutable experiment preregistration."""

from __future__ import annotations

from collections.abc import Iterable
from .base import ResearchArtifact, artifact, nonempty_text, unique_text


def register_research_hypothesis(
    *,
    hypothesis_id: str,
    mechanism_claim: str,
    falsification_rule: str,
) -> ResearchArtifact:
    return artifact(
        "research-hypothesis",
        {
            "hypothesis_id": nonempty_text(hypothesis_id, "hypothesis_id"),
            "mechanism_claim": nonempty_text(mechanism_claim, "mechanism_claim"),
            "falsification_rule": nonempty_text(
                falsification_rule, "falsification_rule"
            ),
        },
    )


def freeze_analysis_plan(
    *,
    metrics: Iterable[str],
    statistical_tests: Iterable[str],
    stopping_rules: Iterable[str],
    selection_rules: Iterable[str],
) -> ResearchArtifact:
    return artifact(
        "analysis-plan",
        {
            "metrics": unique_text(metrics, "metric"),
            "statistical_tests": unique_text(statistical_tests, "statistical_test"),
            "stopping_rules": unique_text(stopping_rules, "stopping_rule"),
            "selection_rules": unique_text(selection_rules, "selection_rule"),
            "immutable": True,
        },
    )


def bind_dataset_cutoff(
    *,
    train_end: str,
    validation_end: str,
    holdout_end: str,
    available_at_field: str = "available_at",
) -> ResearchArtifact:
    train = nonempty_text(train_end, "train_end")
    validation = nonempty_text(validation_end, "validation_end")
    holdout = nonempty_text(holdout_end, "holdout_end")
    if not train < validation < holdout:
        raise ValueError("dataset cutoffs must be strictly ordered")
    return artifact(
        "dataset-cutoff",
        {
            "train_end": train,
            "validation_end": validation,
            "holdout_end": holdout,
            "available_at_field": nonempty_text(
                available_at_field, "available_at_field"
            ),
        },
    )


def publish_preregistered_experiment(
    hypothesis: ResearchArtifact,
    plan: ResearchArtifact,
    cutoff: ResearchArtifact,
    *,
    exploratory: bool = False,
) -> ResearchArtifact:
    return artifact(
        "preregistered-experiment",
        {
            "hypothesis": hypothesis.identity,
            "analysis_plan": plan.identity,
            "dataset_cutoff": cutoff.identity,
            "exploratory": bool(exploratory),
            "definition_mutable": False,
        },
    )


__all__ = [
    "bind_dataset_cutoff",
    "freeze_analysis_plan",
    "publish_preregistered_experiment",
    "register_research_hypothesis",
]
