from pathlib import Path


def test_liquidator_engine_has_no_merge_conflict_markers():
    text = Path("src/ingest/liquidator_engine.py").read_text()
    assert "<<<<<<<" not in text
    assert "=======" not in text
    assert ">>>>>>>" not in text


def test_legacy_liquidation_callback_does_not_call_executor():
    text = Path("src/legacy_arb_bot.py").read_text()
    start = text.index("async def handle_liquidation_opportunity")
    end = text.index("async def handle_epoch_opportunity", start)
    callback = text[start:end]
    assert "execute_liquidation" not in callback
    assert "PR-020 is shadow-only" in callback
