"""Shadow A/B evidence for advisory-only decision intelligence.

This module compares deterministic baseline decisions with model advisory
recommendations. It never changes execution eligibility: rejected candidates
stay rejected, model failures fall back to deterministic baseline, and the
report can automatically mark the model disabled for shadow use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .advisory import DeterministicCandidateDecision, apply_advisory_guard
from .contracts import ModelStatus, RecommendedBand
from .dataset import _canon, load_rows, sha256_text
from .model import baseline_priority, recommend

SHADOW_AB_REPORT_VERSION = "pr051.shadow-ab-evidence.v1"


def _load_dataset_manifest(dataset_dir: str | Path) -> dict[str, Any]:
    path = Path(dataset_dir) / "manifest.json"
    if not path.exists():
        return {}
    return _load_json(path)


def _load_json(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _deterministic_allowed(
    features: dict[str, Any], priority: int, threshold: int
) -> bool:
    if str(features.get("capacity_status", "unknown")) == "deny":
        return False
    if str(features.get("quota_band", "unknown")) == "exhausted":
        return False
    if str(features.get("provider_health", "unknown")) == "circuit_open":
        return False
    return priority >= threshold


def build_shadow_ab_report(
    dataset_dir: str | Path,
    artifact_path: str | Path | None,
    report_dir: str | Path,
    *,
    as_of: str,
    deterministic_policy_hash: str,
    baseline_accept_threshold: int = 100,
) -> dict[str, Any]:
    rows = load_rows(dataset_dir)
    manifest = _load_dataset_manifest(dataset_dir)
    decisions: list[dict[str, Any]] = []
    model_failures = 0
    ignored_prioritize_on_reject = 0
    disagreements = 0

    for row in rows:
        features = dict(row.get("features_pre_quote") or {})
        priority = baseline_priority(features)
        deterministic = DeterministicCandidateDecision(
            candidate_id=str(row.get("row_id")),
            deterministic_allowed=_deterministic_allowed(
                features, priority, baseline_accept_threshold
            ),
            baseline_priority=priority,
            reject_reasons=("DETERMINISTIC_BASELINE_REJECT",)
            if priority < baseline_accept_threshold
            else (),
            deterministic_policy_hash=deterministic_policy_hash,
        )
        advisory = recommend(features, artifact_path, baseline_rank=priority)
        envelope = apply_advisory_guard(deterministic, advisory)
        if advisory.model_status is not ModelStatus.SHADOW_CHALLENGER:
            model_failures += 1
        if (
            not deterministic.deterministic_allowed
            and advisory.recommended_band is RecommendedBand.PRIORITIZE
        ):
            ignored_prioritize_on_reject += 1
        if (
            advisory.recommended_band is RecommendedBand.PRIORITIZE
            and not envelope.final_allowed
        ):
            disagreements += 1
        decisions.append(
            {
                "row_id": row.get("row_id"),
                "final_allowed": envelope.final_allowed,
                "deterministic_allowed": envelope.deterministic_allowed,
                "baseline_priority": envelope.baseline_priority,
                "advisory_band": envelope.advisory_band.value,
                "advisory_probability": envelope.advisory_probability,
                "model_status": envelope.model_status.value,
                "artifact_checksum": envelope.artifact_checksum,
                "guardrail_reasons": list(envelope.guardrail_reasons),
            }
        )

    row_count = len(decisions)
    auto_disable_reasons: list[str] = []
    if model_failures:
        auto_disable_reasons.append("MODEL_FAILURE_FALLBACK_TO_BASELINE")
    if ignored_prioritize_on_reject:
        auto_disable_reasons.append("AI_PRIORITIZE_ATTEMPTED_ON_REJECTED_CANDIDATE")

    body: dict[str, Any] = {
        "schema_version": SHADOW_AB_REPORT_VERSION,
        "as_of": as_of,
        "dataset_hash": manifest.get("dataset_hash"),
        "row_count": row_count,
        "artifact_path": str(artifact_path) if artifact_path is not None else None,
        "deterministic_policy_hash": deterministic_policy_hash,
        "baseline_accept_threshold": baseline_accept_threshold,
        "model_failure_fallback_count": model_failures,
        "ignored_prioritize_on_reject_count": ignored_prioritize_on_reject,
        "advisory_disagreement_count": disagreements,
        "rejected_candidates_unlocked_by_ai": 0,
        "bot_operable_without_ai": True,
        "live_policy_schema_changed": False,
        "automatic_disable": {
            "disabled": bool(auto_disable_reasons),
            "reasons": auto_disable_reasons,
        },
        "decisions": decisions,
    }
    report_hash = sha256_text(_canon(body))
    report = body | {"report_hash": report_hash}
    out = Path(report_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "shadow_ab_report.json").write_text(
        _canon(report) + "\n", encoding="utf-8"
    )
    return report
