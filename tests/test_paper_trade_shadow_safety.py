from src.ingest.data_aggregator import DataAggregator


def test_paper_trade_writer_forces_quote_only_non_executed(tmp_path):
    db = tmp_path / "paper.db"
    agg = DataAggregator(str(db))
    row = agg._sanitize_shadow_paper_trade({"decision": "EXECUTE", "executed": 1, "sim_success": 0})
    assert row["executed"] == 0
    assert row["submitted"] == 0
    assert row["sim_success"] == 0
    assert "quote-only paper record is not executed" in row["sim_error"]
