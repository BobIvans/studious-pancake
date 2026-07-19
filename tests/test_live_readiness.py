# flake8: noqa
from pathlib import Path
from src.execution.live_control import LiveControlStore, LiveMode, LiveReadinessService, canonical_policy_hash, load_policy
from src.execution.journal import SQLiteAttemptJournal

def policy(): return load_policy('config/live_risk.yaml')
def store(tmp_path): return LiveControlStore(tmp_path/'live.sqlite')
def journal(tmp_path): return SQLiteAttemptJournal(tmp_path/'live.sqlite')

def test_default_config_shadow_only_and_full_report(tmp_path):
    p=policy(); s=store(tmp_path); j=journal(tmp_path)
    r=LiveReadinessService(p,s,j).report(LiveMode.LIMITED_LIVE)
    assert not r.passed
    assert {g.name for g in r.gates} >= set(LiveReadinessService.REQUIRED)
    assert next(g for g in r.gates if g.name=='live_enabled').status.value=='FAIL'

def test_hash_stable_and_changes():
    p=policy(); h=canonical_policy_hash(p)
    assert h == canonical_policy_hash(load_policy('config/live_risk.yaml'))
    p['protected_reserve_lamports'] += 1
    assert h != canonical_policy_hash(p)

def test_015_sol_budget_denies(tmp_path):
    p=policy(); p['live_enabled']=True; p['wallet']['observed_lamports']=15_000_000
    s=store(tmp_path); j=journal(tmp_path); s.arm(canonical_policy_hash(p),60)
    r=LiveReadinessService(p,s,j).report(LiveMode.LIMITED_LIVE)
    assert not r.passed
    assert next(g for g in r.gates if g.name=='wallet_reserve').status.value=='FAIL'

def test_discovery_only_provider_cannot_execute(tmp_path):
    p=policy(); p['live_enabled']=True; p['providers']['openocean']['role']='execution'
    s=store(tmp_path); j=journal(tmp_path); s.arm(canonical_policy_hash(p),60)
    assert not LiveReadinessService(p,s,j).report(LiveMode.LIMITED_LIVE).passed
