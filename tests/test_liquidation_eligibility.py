from tests.test_liquidation_adapters import snap
from src.liquidation.adapters import KaminoLiquidationAdapter
from src.liquidation.eligibility import LiquidationEligibilityEngine
from src.liquidation.models import *

def test_stale_oracle_rejects():
    s=snap(); o={'D': OracleSnapshot('pyth',1,1,1,100,0,10,'stale','oh')}
    s=LiquidationTargetSnapshot(s.protocol,s.deployment,s.market,s.target_account,s.slot,s.raw_hash,s.positions,s.risk,o,s.indexer_health_assets,s.indexer_health_liabilities)
    assert LiquidationEligibilityEngine((KaminoLiquidationAdapter(),)).evaluate(s).reason is LiquidationReason.ORACLE_STALE

def test_health_model_mismatch_rejects():
    s=snap(); s=LiquidationTargetSnapshot(s.protocol,s.deployment,s.market,s.target_account,s.slot,s.raw_hash,s.positions,s.risk,s.oracles,1,2)
    assert LiquidationEligibilityEngine((KaminoLiquidationAdapter(),)).evaluate(s).reason is LiquidationReason.HEALTH_MODEL_MISMATCH
