from src.decision.dataset import DecisionDatasetBuilder
from src.decision.model import train_model, evaluate_model


def test_report_contains_metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("DECISION_MODEL_ENABLED", "true")
    DecisionDatasetBuilder().build(
        ["tests/fixtures/pr022/events.jsonl"],
        as_of="2026-01-03T00:00:00+00:00",
        out_dir=tmp_path / "d",
    )
    train_model(tmp_path / "d", tmp_path / "a")
    r = evaluate_model(
        tmp_path / "d", tmp_path / "a", tmp_path / "r", "2026-01-03T00:00:00+00:00"
    )
    assert (
        "brier_score" in r["metrics"]
        and r["baseline_comparison"]["same_untouched_test_window"]
    )
