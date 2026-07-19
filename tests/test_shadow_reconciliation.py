import pytest
from src.execution.shadow import *

def req():
    return SimulationRequest('opp','att','p','mh',b'unsigned:msg',1,('payer',),compiler_diagnostics=CompilerDiagnostics(('payer','vault'),('altw',),('altr',)))

def rep(**kw):
    r=req(); object.__setattr__(r,'message_hash',__import__('hashlib').sha256(b'msg').hexdigest())
    return SimulationReport(r,'https://rpc/?api-key=REDACTED',10,'3.1.8',kw.get('err'),tuple(kw.get('logs',('repay ok',))),None,100,5000,{'writable':('altw',),'readonly':('altr',)},(10000,0,0,0),(12000,0,0,0),kw.get('pre_t',()),kw.get('post_t',()),'rh',kw.get('reason'))

def test_fee_not_double_counted_and_repayment():
    out=ShadowReconciler(min_profit=1000).reconcile(rep(), required_repayment=1)
    assert out.reason == ShadowReason.SHADOW_RECONCILED
    assert out.native_delta == 2000
    assert out.simulated_executable_pnl == 2000
    assert out.fee == 5000

def test_program_error_rejects():
    out=ShadowReconciler().reconcile(rep(err={'InstructionError':[0,'x']}), required_repayment=1)
    assert out.reason == ShadowReason.SIMULATION_PROGRAM_ERROR
    assert not out.complete

def test_loaded_addresses_mismatch_fails_closed():
    bad=rep(); object.__setattr__(bad,'loaded_addresses',{'writable':('wrong',),'readonly':('altr',)})
    out=ShadowReconciler().reconcile(bad)
    assert out.reason == ShadowReason.ACCOUNT_KEYS_MISMATCH

def test_token_2022_integer_amount_and_uiamount_ignored():
    t={'accountIndex':2,'mint':'mint','owner':'owner','programId':TOKEN_2022_PROGRAM_ID,'uiTokenAmount':{'amount':'12','uiAmount':999.9}}
    got=TokenBalanceDecoder().decode((t,), ('payer','vault','ata','x'))
    assert got[('owner','mint',TOKEN_2022_PROGRAM_ID)] == 12

def test_bad_token_amount_rejected():
    with pytest.raises(ValueError):
        TokenBalanceDecoder().decode(({'accountIndex':0,'mint':'m','owner':'o','programId':SPL_TOKEN_PROGRAM_ID,'uiTokenAmount':{'amount':'1.5'}},), ('a',))
