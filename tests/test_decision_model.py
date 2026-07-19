import os
from src.decision.dataset import DecisionDatasetBuilder
from src.decision.model import train_model, recommend, load_artifact
from src.decision.contracts import ModelStatus


def test_insufficient_data_disabled(tmp_path):
    DecisionDatasetBuilder().build(
        ["tests/fixtures/pr022/events.jsonl"],
        as_of="2026-01-01T03:00:00+00:00",
        out_dir=tmp_path / "d",
    )
    art = train_model(tmp_path / "d", tmp_path / "a")
    assert art["model_status"] == ModelStatus.DISABLED_INSUFFICIENT_DATA.value


def test_train_artifact_safe_and_prediction_explainable(tmp_path, monkeypatch):
    DecisionDatasetBuilder().build(
        ["tests/fixtures/pr022/events.jsonl"],
        as_of="2026-01-03T00:00:00+00:00",
        out_dir=tmp_path / "d",
    )
    art = train_model(tmp_path / "d", tmp_path / "a")
    assert load_artifact(tmp_path / "a")["checksum"] == art["checksum"]
    feat = {
        "strategy_family": "lst",
        "opportunity_type": "cycle",
        "route_shape_class": "direct",
        "market_category": "stable",
        "candidate_age_ms": 1,
        "slot_age": 1,
        "provider_health": "healthy",
        "quota_band": "available",
        "capacity_status": "pass",
        "complexity_profile": "low",
        "token2022_flag": "no",
        "historical_success_rate_ppm": 0,
        "historical_reject_rate_ppm": 0,
    }
    assert recommend(feat, tmp_path / "a").model_status == ModelStatus.MODEL_DISABLED
    monkeypatch.setenv("DECISION_MODEL_ENABLED", "true")
    rec = recommend(feat, tmp_path / "a")
    assert rec.advisory_only and rec.baseline_priority > 0
