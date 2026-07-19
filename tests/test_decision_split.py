from src.decision.dataset import DecisionDatasetBuilder, load_rows, parse_utc
from src.decision.split import PurgedGroupedTimeSplit


def test_grouped_time_split_no_group_crossing(tmp_path):
    DecisionDatasetBuilder().build(
        ["tests/fixtures/pr022/events.jsonl"],
        as_of="2026-01-03T00:00:00+00:00",
        out_dir=tmp_path,
    )
    rows = load_rows(tmp_path)
    s = PurgedGroupedTimeSplit(embargo_seconds=0).split(rows)
    by = {r["row_id"]: r for r in rows}
    parts = [s.train_ids, s.calibration_ids, s.test_ids]
    for a in range(3):
        for b in range(a + 1, 3):
            assert {by[i]["lineage_group_id"] for i in parts[a]}.isdisjoint(
                {by[i]["lineage_group_id"] for i in parts[b]}
            )
    assert max(parse_utc(by[i]["candidate_observed_at"]) for i in s.train_ids) < min(
        parse_utc(by[i]["candidate_observed_at"]) for i in s.test_ids
    )
