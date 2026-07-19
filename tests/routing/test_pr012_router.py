from __future__ import annotations
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import pytest
from src.routing import *
from src.routing.adapters import OkxAuth
from src.routing.limiter import FakeClock

SOL="So11111111111111111111111111111111111111112"
USDC="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WALLET="J5CBzXpcYn6WR2JBah8zU4Yxct985CAFGwXRcFaX2pbS"

def req(): return QuoteRequest(SOL, USDC, 1000000, WALLET, 50)

def test_capability_boundary_blocks_assembled_and_quote_only():
    with pytest.raises(TypeError): RawInstructionArtifact(ODOS_CAPABILITIES, instructions=(object(),))
    with pytest.raises(TypeError): RawInstructionArtifact(OPENOCEAN_CAPABILITIES, instructions=(object(),))
    RawInstructionArtifact(JUPITER_CAPABILITIES, instructions=(object(),))

def test_registry_roles_and_missing_credentials_are_isolated():
    report=ProviderRegistry.from_env({}).startup_report()
    states={r["provider"]:r["state"] for r in report}
    assert states == {"jupiter_router":"ready","okx_dex":"disabled_missing_credentials","openocean":"disabled_missing_credentials","odos":"discovery_only"}
    assert {r["artifact_kind"] for r in report} >= {"raw_instructions","assembled_transaction","none"}

def test_okx_hmac_vector_and_params_are_canonical():
    params={"userWalletAddress":WALLET,"chainIndex":"501","amount":"1000000","fromTokenAddress":SOL,"toTokenAddress":USDC,"slippagePercent":"0.5"}
    query=OkxAuth.canonical_query(params)
    assert query.startswith("amount=1000000&chainIndex=501")
    sig=OkxAuth.sign("secret", "2026-07-19T00:00:00.000Z", "GET", "/api/v6/dex/aggregator/swap-instruction?"+query)
    assert sig == "bLuLmyAD4hztejXxgSpcSaJ8NH9/Q1O0lxweiZIc41A="

def test_odos_quote_body_ttl_and_assemble_non_composable():
    clock=FakeClock(datetime(2026,7,19,tzinfo=timezone.utc)); adapter=OdosAdapter(clock=clock)
    body=adapter.quote_body(req())
    assert body["chainId"] == 101 and body["userAddr"] == WALLET and body["inputTokens"][0]["amount"] == "1000000"
    q=adapter.normalize_quote(req(), {"pathId":"path-1","outAmounts":["123"],"sources":["Raydium"]})
    assert q.expires_at == clock.now()+timedelta(seconds=60)
    art=adapter.normalize_assemble({"transaction":"AQIDBA=="})
    assert isinstance(art, AssembledTransactionArtifact)
    with pytest.raises(TypeError): RawInstructionArtifact(art.capabilities, instructions=(object(),))

def test_openocean_missing_key_limiter_unknown_fee_and_dedupe():
    clock=FakeClock(datetime(2026,7,19,tzinfo=timezone.utc)); adapter=OpenOceanAdapter(api_key="key", clock=clock)
    assert adapter.limiter.allow() and adapter.limiter.allow() and not adapter.limiter.allow()
    oo=adapter.normalize(req(), {"inAmount":"1000000","outAmount":"200","sources":["Jupiter"],"traceId":"oo1"})
    assert oo.provider_fee == "unknown" and oo.minimum_output_state is MinimumOutputState.UNPROVEN
    jup=JupiterRouterAdapter(clock=clock).normalize_build(req(), {"inputMint":SOL,"outputMint":USDC,"inAmount":"1000000","outAmount":"190","otherAmountThreshold":"180","slippageBps":50,"routePlan":[{"swapInfo":{"label":"Jupiter"}}],"requestId":"j1"})
    # identical disclosed provenance dedupes when normalized to the same route key
    oo2=replace(oo, route_provenance=jup.route_provenance, artifact_kind=ExecutionArtifactKind.NONE)
    res=RouteDiscoveryService(ProviderRegistry(())).classify((jup, oo2), now=clock.now())
    assert len(res.discovery_candidates) == 1 and res.non_selection_reasons[oo2.external_id] is NonSelectionReason.DUPLICATE

def test_okx_normalization_is_discovery_only_until_promotion_gate():
    adapter=OkxDexAdapter(api_key="k", passphrase="p", secret="s")
    payload={"code":"0","data":{"instructionLists":[{"data":"AQID","accounts":[{"isSigner":True,"isWritable":True,"pubkey":WALLET}],"programId":"11111111111111111111111111111111"}],"addressLookupTableAccount":[WALLET],"routerResult":{"chainIndex":"501","fromTokenAmount":"1000000","toTokenAmount":"250","tradeFee":"0.01","dexRouterList":[],"tx":{"minReceiveAmount":"240"}}}}
    q=adapter.normalize(req(), payload)
    assert q.artifact_kind is ExecutionArtifactKind.RAW_INSTRUCTIONS
    res=RouteDiscoveryService(ProviderRegistry(())).classify((q,))
    assert not res.executable_candidates and res.non_selection_reasons[q.external_id] is NonSelectionReason.NON_COMPOSABLE

def test_selection_uses_conservative_net_not_raw_out():
    clock=FakeClock(datetime(2026,7,19,tzinfo=timezone.utc)); adapter=JupiterRouterAdapter(clock=clock)
    a=adapter.normalize_build(req(), {"inputMint":SOL,"outputMint":USDC,"inAmount":"1000000","outAmount":"1000","otherAmountThreshold":"900","slippageBps":50,"routePlan":[{"swapInfo":{"label":"A"}}],"contextSlot":1,"requestId":"a"})
    b=adapter.normalize_build(req(), {"inputMint":SOL,"outputMint":USDC,"inAmount":"1000000","outAmount":"950","otherAmountThreshold":"940","slippageBps":50,"routePlan":[{"swapInfo":{"label":"B"}}],"contextSlot":2,"requestId":"b"})
    sel=RouteDiscoveryService(ProviderRegistry(())).select_executable((replace(a, conservative_net_result=10), replace(b, conservative_net_result=20)))
    assert sel.selected.external_id == "b"
