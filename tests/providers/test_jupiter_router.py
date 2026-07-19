import json, asyncio, pytest
from pathlib import Path

from src.providers.jupiter.router import *
from src.execution.models import SimulationReport

FIX=Path('tests/fixtures/providers/jupiter/router_build_success_2026-07-19.json')
REQ=JupiterBuildRequest(input_mint='So11111111111111111111111111111111111111112', output_mint='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v', amount=1000000, taker='Takr111111111111111111111111111111111111111', slippage_bps=100, wrap_and_unwrap_sol=False)

def load(name='router_build_success_2026-07-19.json'):
    return json.loads(Path('tests/fixtures/providers/jupiter/'+name).read_text())

def test_schema_preserves_account_meta_flags_and_buckets():
    b=parse_build_response(load(), REQ)
    assert b.compute_unit_price_instructions[0].program_id == COMPUTE_BUDGET_PROGRAM_ID
    assert b.setup_instructions[0].accounts[0].is_signer is True
    assert b.setup_instructions[0].accounts[0].is_writable is True
    assert b.swap_instruction.accounts[0].is_signer is True
    assert b.swap_instruction.accounts[0].is_writable is False
    assert b.cleanup_instruction is None and b.tip_instruction is None
    assert b.addresses_by_lookup_table_address['ALT1111111111111111111111111111111111111111'][0].startswith('Pool')
    assert b.execution_buckets()['swap'][0].data == b'swap'

def test_rejects_unknown_schema_and_unexpected_tip():
    with pytest.raises(JupiterRouterError) as e: parse_build_response(load('router_build_unknown_field_2026-07-19.json'), REQ)
    assert e.value.reason == JupiterRejectionReason.SCHEMA_FAILURE
    with pytest.raises(JupiterRouterError) as e: parse_build_response(load('router_build_unexpected_tip_2026-07-19.json'), REQ)
    assert e.value.reason == JupiterRejectionReason.UNSAFE_TIP

def test_request_params_are_get_build_safe_and_no_tip_amount():
    p=REQ.to_params()
    assert p['amount'] == '1000000'
    assert p['wrapAndUnwrapSol'] == 'false'
    assert 'tipAmount' not in p and 'platformFeeBps' not in p
    assert 'dexes' not in p

def test_config_repr_redacts_secret_ref_value():
    r=repr(JupiterRouterConfig(api_key_secret_ref='SECRET_VALUE_SHOULD_NOT_PRINT'))
    assert 'SECRET_VALUE_SHOULD_NOT_PRINT' not in r and '<redacted>' in r

@pytest.mark.asyncio
async def test_missing_credentials_disable_and_do_not_reserve():
    q=JupiterQuotaManager(limit=60, window_seconds=60, finalization_reserve=4)
    a=JupiterRouterAdapter(JupiterRouterConfig(), q, api_key='')
    assert a.status()['health'] == 'disabled_missing_credentials'
    with pytest.raises(JupiterRouterError) as e: await a.build(None, REQ)  # type: ignore[arg-type]
    assert e.value.reason == JupiterRejectionReason.MISSING_CREDENTIALS
    assert q.metrics.reserved == 0

@pytest.mark.asyncio
async def test_quota_sliding_window_and_finalization_reserve():
    t=[0.0]
    qm=JupiterQuotaManager(limit=60, window_seconds=60, finalization_reserve=4, clock=lambda: t[0])
    for _ in range(56): await qm.reserve('discovery')
    with pytest.raises(JupiterRouterError): await qm.reserve('discovery')
    for _ in range(4): await qm.reserve('finalization')
    with pytest.raises(JupiterRouterError): await qm.reserve('finalization')
    t[0]=61
    await qm.reserve('discovery')

def test_cu_limit_policy():
    r=SimulationReport(success=True,error=None,logs=(),inner_instructions=None,units_consumed=1000,loaded_accounts_data_size=None,return_data=None,pre_account_states=(),post_account_states=(),token_deltas=(),native_delta_before_fee=0,estimated_network_fee=0,simulated_net_profit=None,simulation_slot=0,min_context_slot=0,transaction_message_hash='h')
    assert calculate_final_cu_limit(r) == 1200
    r2=SimulationReport(success=True,error=None,logs=(),inner_instructions=None,units_consumed=2_000_000,loaded_accounts_data_size=None,return_data=None,pre_account_states=(),post_account_states=(),token_deltas=(),native_delta_before_fee=0,estimated_network_fee=0,simulated_net_profit=None,simulation_slot=0,min_context_slot=0,transaction_message_hash='h')
    assert calculate_final_cu_limit(r2) == 1_400_000
    r3=SimulationReport(success=True,error=None,logs=(),inner_instructions=None,units_consumed=None,loaded_accounts_data_size=None,return_data=None,pre_account_states=(),post_account_states=(),token_deltas=(),native_delta_before_fee=0,estimated_network_fee=0,simulated_net_profit=None,simulation_slot=0,min_context_slot=0,transaction_message_hash='h')
    with pytest.raises(JupiterRouterError): calculate_final_cu_limit(r3)


def test_two_leg_composition_and_fallback_sequence():
    from src.providers.jupiter.policy import compose_two_leg_plan, fallback_sequence, FallbackAction
    b1=parse_build_response(load(), REQ)
    req2=JupiterBuildRequest(input_mint=REQ.output_mint, output_mint=REQ.input_mint, amount=b1.other_amount_threshold, taker=REQ.taker, slippage_bps=100)
    data=load(); data['inputMint']=req2.input_mint; data['outputMint']=req2.output_mint; data['inAmount']=str(req2.amount)
    b2=parse_build_response(data, req2)
    plan=compose_two_leg_plan(b1,b2)
    assert [ix.kind for ix in (*plan.setup, *plan.leg1, *plan.leg2, *plan.cleanup)] == ['setup','setup','swap','swap']
    attempts=fallback_sequence('trace-1', (64,56,50,48), allow_below_50=False, direct_route_verified=True)
    assert attempts[0].action == FallbackAction.REMOVE_PROVEN_REDUNDANT_SETUP
    assert [a.max_accounts for a in attempts if a.action == FallbackAction.REBUILD_SMALLER_ACCOUNT_BUDGET] == [56,50]
    assert all(a.max_accounts >= 50 for a in attempts)
