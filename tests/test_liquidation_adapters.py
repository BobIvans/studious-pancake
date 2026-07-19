from src.liquidation.adapters import KaminoLiquidationAdapter, MarginFiLiquidationAdapter
from src.liquidation.models import *

def snap(protocol=LendingProtocol.KAMINO_LEND, assets=90, liab=100):
    dep=ProtocolDeploymentSpec(protocol,'mainnet-beta','Prog','v','src','commit','idl','2026-07-19',True)
    risk=RiskConfigSnapshot(1000,50,250,10,10,assets,liab,'risk')
    oracle={'D': OracleSnapshot('pyth',1,1,1,100,0,10,'fresh','oh')}
    pos=(PositionSnapshot('D','debt-bank',100,6,'debt'),PositionSnapshot('C','coll-bank',200,6,'collateral'))
    return LiquidationTargetSnapshot(protocol,dep,'market','target',10,'raw',pos,risk,oracle,assets,liab)

def test_kamino_adapter_uses_snapshot_close_factor_not_generic_bonus():
    ev=KaminoLiquidationAdapter().evaluate(snap())
    assert ev.status is LiquidationStatus.POTENTIALLY_LIQUIDATABLE
    assert ev.max_repay == 10

def test_marginfi_health_zero_or_less_semantics():
    ev=MarginFiLiquidationAdapter().evaluate(snap(LendingProtocol.MARGINFI_V2, 100, 100))
    assert ev.status is LiquidationStatus.POTENTIALLY_LIQUIDATABLE

def test_disabled_deployment_rejects():
    s=snap(); dep=ProtocolDeploymentSpec(s.protocol,'mainnet-beta','Prog','v','src','commit','idl','2026-07-19',False,LiquidationReason.LIQUIDATION_DEPLOYMENT_MISMATCH)
    s=LiquidationTargetSnapshot(s.protocol,dep,s.market,s.target_account,s.slot,s.raw_hash,s.positions,s.risk,s.oracles,s.indexer_health_assets,s.indexer_health_liabilities)
    assert KaminoLiquidationAdapter().evaluate(s).reason is LiquidationReason.LIQUIDATION_DEPLOYMENT_MISMATCH
