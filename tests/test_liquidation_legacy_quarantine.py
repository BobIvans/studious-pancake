import pytest

from src.ingest.liquidator_engine import LiquidationEngine


@pytest.mark.asyncio
async def test_legacy_execute_liquidation_is_immediate_quarantine():
    engine = LiquidationEngine("ws://127.0.0.1:8900", "kamino", "marginfi", None)
    with pytest.raises(RuntimeError, match="quarantined"):
        await engine.execute_liquidation(None, 0, None)
