import json
from src.decision.dataset import DecisionDatasetBuilder
from src.decision.model import train_model, replay_quota


def test_quota_replay_preserves_exploration(tmp_path, monkeypatch):
    monkeypatch.setenv("DECISION_MODEL_ENABLED", "true")
    DecisionDatasetBuilder().build(
        ["tests/fixtures/pr022/events.jsonl"],
        as_of="2026-01-03T00:00:00+00:00",
        out_dir=tmp_path / "d",
    )
    train_model(tmp_path / "d", tmp_path / "a")
    out = replay_quota(
        tmp_path / "d", tmp_path / "a", {"budget": 5, "exploration_share": 0.4}
    )
    assert len(out["selected_row_ids"]) == 5 and out["provider_limits_preserved"]
