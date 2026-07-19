import base64, hmac, hashlib
from datetime import timedelta

import pytest

from src.domain.money import BasisPoints, TOKEN_2022_PROGRAM, TOKEN_PROGRAM, TokenAmount, NATIVE_SOL_MINT, WSOL_MINT
from src.ingest.swap_providers import *

USDC="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WALLET="11111111111111111111111111111111"

def req(**kw):
    data=dict(input_mint=USDC, output_mint=WSOL_MINT, amount=TokenAmount(USDC, 1000, 6), swap_mode=SwapMode.EXACT_IN, taker=WALLET, payer=WALLET, slippage_bps=BasisPoints(50))
    data.update(kw)
    return QuoteRequest(**data)

def test_jupiter_removed_bad_endpoints_and_uses_build():
    assert JupiterSwapV2Adapter.endpoint == "https://api.jup.ag/swap/v2/build"
    assert "/swap/v2/quote" not in JupiterSwapV2Adapter.endpoint
    assert "/swap/v2/swap" not in JupiterSwapV2Adapter.endpoint
    assert JupiterSwapV2Adapter().rps == 0.5

def test_generic_response_parsing_removed_from_facade_source():
    import pathlib
    source = pathlib.Path("src/ingest/multi_aggregator_client.py").read_text()
    assert '.get("data", {}).get("outAmount")' not in source
    assert "Odos" not in source and "odos.xyz" not in source

def test_openocean_cannot_execute_without_verified_contract():
    oo=OpenOceanSolanaAdapter()
    assert not (oo.capabilities & SwapCapability.RAW_INSTRUCTIONS)
    with pytest.raises(UnsupportedProviderCapability):
        import asyncio
        asyncio.run(oo.instructions(None, None))

def test_0x_rejects_token_2022_and_native_sol():
    zx=ZeroXSolanaAdapter(enabled=True)
    with pytest.raises(UnsupportedProviderCapability):
        zx._validate_request_capabilities(req(token_program=TOKEN_2022_PROGRAM))
    with pytest.raises(UnsupportedProviderCapability):
        zx._validate_request_capabilities(req(input_mint=NATIVE_SOL_MINT))

def test_okx_auth_signature():
    okx=OKXSolanaAdapter("key","secret","pass")
    ts="2026-07-19T00:00:00.000Z"; path="/api/v6/dex/aggregator/swap-instruction"
    headers=okx.auth_headers("GET", path, "", ts)
    expected=base64.b64encode(hmac.new(b"secret", f"{ts}GET{path}".encode(), hashlib.sha256).digest()).decode()
    assert headers["OK-ACCESS-KEY"] == "key"
    assert headers["OK-ACCESS-PASSPHRASE"] == "pass"
    assert headers["OK-ACCESS-SIGN"] == expected

def test_odos_not_active_and_no_hardcoded_provider_wallet():
    names=[p.name for p in active_solana_providers()]
    assert "odos" not in names and "odos_solana" not in names
    import pathlib
    text=pathlib.Path("src/ingest/swap_providers.py").read_text()+pathlib.Path("src/ingest/multi_aggregator_client.py").read_text()
    assert "Fk4G5NB5e1NyULQCCpTNLWCmChCW2UbDwpkEofqAiHk2" not in text

def test_quote_only_provider_cannot_enter_execution_shortlist():
    oo=OpenOceanSolanaAdapter(); j=JupiterSwapV2Adapter()
    q=NormalizedQuote("openocean_solana", req(), TokenAmount(WSOL_MINT,1,6), TokenAmount(WSOL_MINT,1,6), SwapMode.EXACT_IN, (), (), "none", {}, __import__('time').time())
    assert execution_shortlist([q], {"openocean_solana": oo, "jupiter_swap_v2": j}) == ()

def test_selection_requires_successful_simulation():
    import inspect
    src=inspect.getsource(select_after_simulation)
    assert "sim.success" in src
    assert "use_simulated=True" in src
