import json
from src.decision.dataset import DecisionDatasetBuilder, load_rows


def test_dataset_build_reproducible_and_counts(tmp_path):
    m1 = DecisionDatasetBuilder().build(
        ["tests/fixtures/pr022/events.jsonl"],
        as_of="2026-01-03T00:00:00+00:00",
        out_dir=tmp_path / "a",
    )
    m2 = DecisionDatasetBuilder().build(
        ["tests/fixtures/pr022/events.jsonl"],
        as_of="2026-01-03T00:00:00+00:00",
        out_dir=tmp_path / "b",
    )
    assert m1["dataset_hash"] == m2["dataset_hash"]
    assert m1["positive_count"] > 0 and m1["negative_count"] > 0
    row = load_rows(tmp_path / "a")[0]
    assert set(row).issuperset(
        {
            "features_pre_quote",
            "label_status",
            "lineage_group_id",
            "source_event_hashes",
        }
    )


def test_forbidden_prequote_feature_rejected(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text(
        json.dumps(
            {
                "event_id": "c",
                "event_type": "candidate_observed",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "root_opportunity_id": "r",
                "features_pre_quote": {"final_pnl": 1},
            }
        )
        + "\n"
    )
    m = DecisionDatasetBuilder().build(
        [p], as_of="2026-01-02T00:00:00+00:00", out_dir=tmp_path / "d"
    )
    assert m["excluded_counts"]["forbidden_feature"] == 1
