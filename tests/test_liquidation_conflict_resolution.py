from pathlib import Path


def test_liquidator_engine_has_no_merge_conflict_markers():
    text = Path("src/ingest/liquidator_engine.py").read_text()
    assert "<<<<<<<" not in text
    assert "=======" not in text
    assert ">>>>>>>" not in text
    assert "legacy LiquidationEngine.execute_liquidation is quarantined" in text
