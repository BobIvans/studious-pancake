from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.decision.advisory import (
    DeterministicCandidateDecision,
    apply_advisory_guard,
    assert_no_ai_control_surface,
)
from src.decision.contracts import (
    FEATURE_SPEC_VERSION,
    MODEL_ARTIFACT_VERSION,
    DecisionStage,
    ModelStatus,
    RankingRecommendation,
    RecommendedBand,
)
from src.decision.dataset import DecisionDatasetBuilder, _canon, sha256_text
from src.decision.model_registry import build_model_registry
from src.decision.shadow_ab import build_shadow_ab_report

pytestmark = pytest.mark.unit


def _features(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "strategy_family": "fixture",
        "opportunity_type": "shadow",
        "route_shape_class": "two_leg",
        "market_category": "allowlisted_fixture",
        "candidate_age_ms": 10,
        "slot_age": 1,
        "provider_health": "healthy",
        "quota_band": "available",
        "capacity_status": "pass",
        "complexity_profile": "low",
        "token2022_flag": "no",
        "historical_success_rate_ppm": 500_000,
        "historical_reject_rate_ppm": 500_000,
    }
    base.update(overrides)
    return base


def _write_jsonl(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text("\n".join(_canon(event) for event in events) + "\n", encoding="utf-8")


def test_dataset_rejects_wallet_and_api_secrets_before_hashing(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_jsonl(
        events_path,
        [
            {
                "event_id": "candidate-1",
                "event_type": "candidate_observed",
                "timestamp": "2026-07-20T00:00:00Z",
                "root_opportunity_id": "opp-1",
                "source_slot": 1,
                "observation_sequence": 1,
                "api_key": "sk-do-not-store",
                "features_pre_quote": _features(),
            }
        ],
    )

    manifest = DecisionDatasetBuilder().build(
        [events_path], as_of="2026-07-21T00:00:00Z", out_dir=tmp_path / "dataset"
    )

    assert manifest["row_count"] == 0
    assert manifest["source_event_count"] == 0
    assert manifest["excluded_counts"] == {"secret_rejected": 1}
    assert (tmp_path / "dataset" / "rows.jsonl").read_text(encoding="utf-8") == ""


def test_ai_advisory_output_cannot_unlock_rejected_candidate() -> None:
    recommendation = RankingRecommendation(
        artifact_version=MODEL_ARTIFACT_VERSION,
        stage=DecisionStage.PRE_QUOTE,
        probability=0.99,
        baseline_priority=999,
        recommended_band=RecommendedBand.PRIORITIZE,
        explanations=("fixture-positive",),
        model_status=ModelStatus.SHADOW_CHALLENGER,
        artifact_checksum="abc123",
    )
    deterministic = DeterministicCandidateDecision(
        candidate_id="candidate-1",
        deterministic_allowed=False,
        baseline_priority=10,
        reject_reasons=("MIN_PROFIT_FAIL",),
        deterministic_policy_hash="policy-hash",
    )

    envelope = apply_advisory_guard(deterministic, recommendation)

    assert envelope.final_allowed is False
    assert envelope.deterministic_allowed is False
    assert "AI_PRIORITIZE_IGNORED_FOR_REJECTED_CANDIDATE" in envelope.guardrail_reasons
    assert envelope.deterministic_policy_hash == "policy-hash"


def test_ai_payload_cannot_reference_control_surfaces() -> None:
    assert_no_ai_control_surface({"advisory_reason": "healthy route"})
    with pytest.raises(ValueError, match="forbidden controls"):
        assert_no_ai_control_surface({"min_profit_override": 1, "sender": "enabled"})


def test_shadow_ab_model_failure_falls_back_and_auto_disables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    row = {
        "row_id": "row-1",
        "features_pre_quote": _features(capacity_status="deny"),
        "label_status": "LABELED",
        "label_value": 0,
        "candidate_observed_at": "2026-07-20T00:00:00Z",
        "lineage_group_id": "g1",
    }
    rows_body = _canon(row) + "\n"
    (dataset_dir / "rows.jsonl").write_text(rows_body, encoding="utf-8")
    (dataset_dir / "manifest.json").write_text(
        _canon({"dataset_hash": sha256_text(rows_body), "row_count": 1}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DECISION_MODEL_ENABLED", "true")

    report = build_shadow_ab_report(
        dataset_dir,
        tmp_path / "missing-artifact.json",
        tmp_path / "report",
        as_of="2026-07-21T00:00:00Z",
        deterministic_policy_hash="policy-hash",
    )

    assert report["bot_operable_without_ai"] is True
    assert report["model_failure_fallback_count"] == 1
    assert report["rejected_candidates_unlocked_by_ai"] == 0
    assert report["automatic_disable"] == {
        "disabled": True,
        "reasons": ["MODEL_FAILURE_FALLBACK_TO_BASELINE"],
    }
    assert report["live_policy_schema_changed"] is False


def test_model_registry_is_hash_pinned_and_advisory_only(tmp_path: Path) -> None:
    artifact = {
        "artifact_version": MODEL_ARTIFACT_VERSION,
        "feature_spec_version": FEATURE_SPEC_VERSION,
        "created_at": "2026-07-21T00:00:00Z",
        "model_status": ModelStatus.DISABLED_INSUFFICIENT_DATA.value,
        "reason": "fixture",
        "source_dataset_hash": "dataset-hash",
        "evaluation_report_hash": "evaluation-hash",
    }
    artifact["checksum"] = sha256_text(_canon(artifact))
    path = tmp_path / "artifact.json"
    path.write_text(_canon(artifact) + "\n", encoding="utf-8")

    registry = build_model_registry([path])

    assert registry.live_policy_schema_changed is False
    assert registry.runtime_promotion_allowed is False
    assert registry.entries[0].artifact_checksum == artifact["checksum"]
    assert registry.entries[0].advisory_only is True
