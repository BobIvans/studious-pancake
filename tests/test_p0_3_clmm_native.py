"""P0-3 Raydium CLMM native decoder + exact-in math: differential fixtures.

Positive expectations are hand-derived in this file from the pinned vendor
formulas (vendor-reference/raydium/clmm, Apache-2.0, commit 6d7a0f82) written
out independently of the provider module; negative fixtures prove fail-closed
behavior on unknown layouts, truncation, wrong owners, stale slots, paused
pools and unsupported token programs. Zero network, no signer.
"""

from __future__ import annotations

import base64

import pytest
from solders.pubkey import Pubkey

from tests.native_cpmm_fixtures import rehash
from tests.p0_3_fixtures import (
    BLOCK_TIME,
    CLMM_PROGRAM,
    SLOT,
    address,
    build_clmm_accounts,
    clmm_capture,
)
from src.providers.raydium_clmm_native import (
    AMM_CONFIG_LEN,
    ClmmCaptureError,
    compute_swap_step,
    decode_clmm_capture,
    clmm_exact_in_quote,
    check_current_tick_array_is_initialized,
    check_is_valid_start_index,
    decode_tick_array,
    get_next_sqrt_price_from_input,
    get_sqrt_price_at_tick,
    get_tick_at_sqrt_price,
    is_overflow_default_bitmap,
    MAX_SQRT_PRICE_X64,
    MIN_SQRT_PRICE_X64,
    MIN_TICK,
    MAX_TICK,
    next_initialized_tick_array_start_index,
    array_start_index,
    POOL_STATE_LEN,
)
from src.strategy.exact_cpmm_capacity import MAINNET_GENESIS, SPL_TOKEN_PROGRAM

pytestmark = pytest.mark.unit

TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC9PHnBqCXEpPxuEb"

# Pool liquidity model (raw u128 units):
# position A spans [0, 10], B spans [10, 20], C spans [-10, 0], D spans [20, 30].
L_A = 800_000_000_000
L_B = 500_000_000_000
L_C = 600_000_000_000
L_D = 700_000_000_000
NETS = {
    -10: (L_C, L_C),
    0: (L_A - L_C, L_A + L_C),
    10: (L_B - L_A, L_A + L_B),
    20: (L_D - L_B, L_B + L_D),
    30: (-L_D, L_D),
}

CONFIG_KEY = address(70)
MINT0 = address(3)
MINT1 = address(4)
VAULT0 = address(20)
VAULT1 = address(21)
POOL, POOL_BUMP = Pubkey.find_program_address(
    [
        b"pool",
        bytes(Pubkey.from_string(CONFIG_KEY)),
        bytes(Pubkey.from_string(MINT0)),
        bytes(Pubkey.from_string(MINT1)),
        b"",
    ],
    Pubkey.from_string(CLMM_PROGRAM),
)
POOL = str(POOL)


def _div_ceil(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def _delta0_up(a: int, b: int, liquidity: int) -> int:
    """[PINNED swap_math.rs two-step ceil] token 0 delta, a < b, round up."""
    n1 = liquidity << 64
    n2 = b - a
    first = _div_ceil(n1 * n2, b)
    return _div_ceil(first, a)


def _delta0_down(a: int, b: int, liquidity: int) -> int:
    n1 = liquidity << 64
    n2 = b - a
    return (n1 * n2 // b) // a


def _delta1_down(a: int, b: int, liquidity: int) -> int:
    return (liquidity * (b - a)) >> 64


def _delta1_up(a: int, b: int, liquidity: int) -> int:
    return _div_ceil(liquidity * (b - a), 1 << 64)


def _sqrt_next_down(sqrt_current: int, liquidity: int, net_in: int) -> int:
    """[DOCUMENTED sqrt_price_math] zfo next sqrt price, floored."""
    return (
        (liquidity << 64) * sqrt_current // ((liquidity << 64) + net_in * sqrt_current)
    )


def _sqrt_next_up(sqrt_current: int, liquidity: int, net_in: int) -> int:
    return sqrt_current + _div_ceil(net_in << 64, liquidity)


def make_capture(**overrides) -> dict:
    params = dict(
        config_key=CONFIG_KEY,
        pool_key=POOL,
        pool_bump=POOL_BUMP,
        mint0=MINT0,
        mint1=MINT1,
        vault0=VAULT0,
        vault1=VAULT1,
        tick_spacing=10,
        liquidity=L_B,
        sqrt_price_x64=get_sqrt_price_at_tick(10),
        tick_current=10,
        fee_on=0,
        status=0,
        ticks=NETS,
        bitmap_bits=[512],
        include_array_starts=[0, -600],
    )
    params.update(overrides)
    accounts = build_clmm_accounts(**params)
    return clmm_capture(accounts, str(params["pool_key"]))


def find_account(payload: dict, key: str) -> dict:
    return next(e for e in payload["accounts"] if e["address"] == key)


def mutate(payload: dict, key: str, change) -> None:
    entry = find_account(payload, key)
    data = bytearray(base64.b64decode(entry["value"]["data"][0]))
    change(data)
    entry["value"]["data"][0] = base64.b64encode(data).decode()
    rehash(payload)


def tick_array_keys(payload: dict) -> tuple[str, ...]:
    from src.providers.raydium_clmm_native import RAYDIUM_CLMM_PROGRAM_ID

    return tuple(
        e["address"]
        for e in payload["accounts"]
        if e["value"]["owner"] == RAYDIUM_CLMM_PROGRAM_ID
        and e["address"] not in (CONFIG_KEY, POOL)
    )


# ---------------------------------------------------------------------------
# Pinned tick math units
# ---------------------------------------------------------------------------


def test_pinned_sqrt_price_anchors_and_round_trip():
    assert get_sqrt_price_at_tick(0) == 1 << 64
    assert get_sqrt_price_at_tick(MIN_TICK) == MIN_SQRT_PRICE_X64
    assert get_sqrt_price_at_tick(MAX_TICK) == MAX_SQRT_PRICE_X64
    for tick in (-443636, -100000, -600, -1, 0, 1, 600, 100000, 443635, 123456):
        assert get_tick_at_sqrt_price(get_sqrt_price_at_tick(tick)) == tick, tick
    for tick in (-500, 0, 7, 42, 300000):
        inside = get_sqrt_price_at_tick(tick) + 1
        if inside < MAX_SQRT_PRICE_X64:
            assert get_tick_at_sqrt_price(inside) == tick, tick


def test_pinned_bitmap_helpers():
    bitmap = (1 << 512) | (1 << 513)
    assert check_current_tick_array_is_initialized(bitmap, 0, 10) == (True, 0)
    assert check_current_tick_array_is_initialized(bitmap, -1, 10) == (False, -600)
    assert next_initialized_tick_array_start_index(bitmap, 0, 10, False) == (True, 600)
    assert next_initialized_tick_array_start_index(bitmap, 0, 10, True) == (
        False,
        -307200,
    )
    assert next_initialized_tick_array_start_index(bitmap, 600, 10, True) == (True, 0)
    assert array_start_index(-1, 10) == -600
    assert array_start_index(-601, 10) == -1200
    assert check_is_valid_start_index(0, 10) is True
    assert check_is_valid_start_index(10, 10) is False
    assert check_is_valid_start_index(-444000, 10) is True
    assert is_overflow_default_bitmap(30719, 1) is False
    assert is_overflow_default_bitmap(30720, 1) is True
    assert is_overflow_default_bitmap(-30720, 1) is False
    assert is_overflow_default_bitmap(-30721, 1) is True
    assert is_overflow_default_bitmap(443580, 60) is False


def test_pinned_compute_swap_step_target_fee_formula():
    s10 = get_sqrt_price_at_tick(10)
    s0 = get_sqrt_price_at_tick(0)
    step = compute_swap_step(
        s10, s0, L_A, 10**18, 2500, zero_for_one=True, is_fee_on_input=True
    )
    assert step.sqrt_price_next_x64 == s0
    in_net = _delta0_up(s0, s10, L_A)
    assert step.amount_in == in_net
    assert step.amount_out == _delta1_down(s0, s10, L_A)
    assert step.fee_amount == _div_ceil(in_net * 2500, 997_500)


# ---------------------------------------------------------------------------
# Positive differential fixtures (hand-verified)
# ---------------------------------------------------------------------------


def test_capture_decode_and_identity():
    capture = decode_clmm_capture(make_capture())
    assert capture.pool.address == POOL
    assert capture.pool.liquidity == L_B
    assert capture.mints == (MINT0, MINT1)
    assert capture.mint_decimals == (9, 6)
    assert capture.vault_amounts == (10**12, 10**12)
    assert capture.slot == SLOT
    assert capture.block_time == BLOCK_TIME
    assert capture.config.trade_fee_rate == 2500
    assert capture.config.tick_spacing == 10
    assert capture.evidence_kind == "synthetic-fixture"
    assert len(capture.tick_arrays) == 2


def test_partial_step_zero_for_one_hand_verified():
    capture = decode_clmm_capture(make_capture())
    amount_in = 1_000_000
    quote = clmm_exact_in_quote(capture, amount_in, zero_for_one=True)
    # After the zero-width cross of tick 10 the walk runs over [0, 10) with L_A.
    sqrt_next = _sqrt_next_down(get_sqrt_price_at_tick(10), L_A, 997_500)
    in_net = _delta0_up(sqrt_next, get_sqrt_price_at_tick(10), L_A)
    out = _delta1_down(sqrt_next, get_sqrt_price_at_tick(10), L_A)
    fee = amount_in - in_net
    assert quote.amount_out == out
    assert quote.trade_fee == fee
    assert quote.next_sqrt_price_x64 == sqrt_next
    assert quote.next_liquidity == L_A
    assert quote.next_tick_current == 9
    assert quote.tick_crossings == 1
    assert quote.input_left == 0
    assert quote.fee_on_input is True
    assert quote.protocol_fee == fee * 100_000 // 1_000_000
    assert quote.fund_fee == fee * 40_000 // 1_000_000
    assert quote.lp_fee == fee - quote.protocol_fee - quote.fund_fee
    assert len(quote.tick_arrays_used) == 1
    assert quote.tick_arrays_used[0] in tick_array_keys(make_capture())
    assert in_net + fee == amount_in  # conservation


def test_multi_tick_crossing_hand_verified():
    capture = decode_clmm_capture(make_capture())
    s10 = get_sqrt_price_at_tick(10)
    s0 = get_sqrt_price_at_tick(0)
    in_net1 = _delta0_up(s0, s10, L_A)
    out1 = _delta1_down(s0, s10, L_A)
    fee1 = _div_ceil(in_net1 * 2500, 997_500)
    amount = in_net1 + fee1 + 250_000
    # [PINNED] fee-on-input deducts the fee before the price calculation:
    # amount_for_price_calc = floor(250_000 * 997_500 / 1_000_000) = 249_375.
    net_for_price2 = 250_000 * 997_500 // 1_000_000
    sqrt_next2 = _sqrt_next_down(s0, L_C, net_for_price2)
    in_net2 = _delta0_up(sqrt_next2, s0, L_C)
    out2 = _delta1_down(sqrt_next2, s0, L_C)
    fee2 = 250_000 - in_net2
    quote = clmm_exact_in_quote(capture, amount, zero_for_one=True)
    assert quote.amount_out == out1 + out2
    assert quote.trade_fee == fee1 + fee2
    assert quote.tick_crossings == 2
    assert quote.next_liquidity == L_C
    assert quote.next_tick_current == -1
    assert quote.next_sqrt_price_x64 == sqrt_next2
    assert len(quote.tick_arrays_used) == 2


def test_one_for_zero_fee_on_output_hand_verified():
    # fee_on=1 (Token0Only): swapping token 1 in collects the fee from the
    # token 0 output.
    capture = decode_clmm_capture(make_capture(fee_on=1))
    amount_in = 300_000
    quote = clmm_exact_in_quote(capture, amount_in, zero_for_one=False)
    s10 = get_sqrt_price_at_tick(10)
    sqrt_next = _sqrt_next_up(s10, L_B, amount_in)
    out_gross = _delta0_down(s10, sqrt_next, L_B)
    fee = _div_ceil(out_gross * 2500, 1_000_000)
    assert quote.fee_on_input is False
    assert quote.trade_fee == fee
    assert quote.amount_out == out_gross - fee
    assert quote.next_sqrt_price_x64 == sqrt_next
    assert quote.tick_crossings == 0
    assert quote.next_tick_current == 10
    assert quote.next_liquidity == L_B
    assert quote.input_left == 0


def test_missing_tick_array_is_fail_closed():
    capture = decode_clmm_capture(make_capture(include_array_starts=[0]))
    s10 = get_sqrt_price_at_tick(10)
    s0 = get_sqrt_price_at_tick(0)
    in_net1 = _delta0_up(s0, s10, L_A)
    amount = in_net1 + _div_ceil(in_net1 * 2500, 997_500) + 1
    with pytest.raises(ClmmCaptureError, match="MISSING_TICK_ARRAY"):
        clmm_exact_in_quote(capture, amount, zero_for_one=True)


def test_insufficient_liquidity_is_fail_closed():
    capture = decode_clmm_capture(make_capture())
    with pytest.raises(ClmmCaptureError, match="INSUFFICIENT_LIQUIDITY"):
        clmm_exact_in_quote(capture, 10**15, zero_for_one=True)


# ---------------------------------------------------------------------------
# Negative fixtures (fail-closed)
# ---------------------------------------------------------------------------


def test_wrong_program_owner_rejected():
    payload = make_capture()
    find_account(payload, POOL)["value"]["owner"] = address(1)
    rehash(payload)
    with pytest.raises(ClmmCaptureError, match="owner"):
        decode_clmm_capture(payload)


def test_unknown_discriminator_rejected():
    payload = make_capture()

    def flip(data):
        data[0] ^= 0xFF

    mutate(payload, POOL, flip)
    with pytest.raises(ClmmCaptureError, match="PoolState layout"):
        decode_clmm_capture(payload)


def test_truncated_pool_rejected():
    payload = make_capture()
    entry = find_account(payload, POOL)
    data = base64.b64decode(entry["value"]["data"][0])
    entry["value"]["data"][0] = base64.b64encode(data[:-1]).decode()
    rehash(payload)
    with pytest.raises(ClmmCaptureError, match="PoolState layout"):
        decode_clmm_capture(payload)


def test_wrong_pool_pda_rejected():
    payload = make_capture(pool_key=address(52))
    with pytest.raises(ClmmCaptureError, match="PDA"):
        decode_clmm_capture(payload)


def test_tick_array_pda_and_binding_rejected():
    payload = make_capture()
    array_key = tick_array_keys(payload)[0]

    def unbind(data):
        data[8:40] = bytes(Pubkey.from_string(address(31)))

    mutate(payload, array_key, unbind)
    with pytest.raises(ClmmCaptureError, match="different pool"):
        decode_clmm_capture(payload)


def test_tick_array_initialized_count_mismatch_rejected():
    payload = make_capture()
    array_key = tick_array_keys(payload)[0]

    def wrong_count(data):
        data[10604] = 5

    mutate(payload, array_key, wrong_count)
    with pytest.raises(ClmmCaptureError, match="initialized tick count"):
        decode_clmm_capture(payload)


def test_stale_clock_slot_rejected():
    payload = make_capture()
    payload["slot"] = SLOT + 1
    payload["block"]["parentSlot"] = SLOT
    rehash(payload)
    with pytest.raises(ClmmCaptureError, match="clock slot mismatch"):
        decode_clmm_capture(payload)


def test_incoherent_parent_slot_rejected():
    payload = make_capture()
    payload["block"]["parentSlot"] = SLOT
    rehash(payload)
    with pytest.raises(ClmmCaptureError, match="parent slot"):
        decode_clmm_capture(payload)


def test_paused_swap_rejected():
    payload = make_capture(status=16)
    with pytest.raises(ClmmCaptureError, match="disabled"):
        decode_clmm_capture(payload)


def test_unknown_status_bits_rejected():
    payload = make_capture(status=64)
    with pytest.raises(ClmmCaptureError, match="status bits"):
        decode_clmm_capture(payload)


def test_token_2022_mint_rejected():
    payload = make_capture()
    find_account(payload, MINT0)["value"]["owner"] = TOKEN_2022
    rehash(payload)
    with pytest.raises(ClmmCaptureError, match="owner"):
        decode_clmm_capture(payload)


def test_nonzero_dynamic_fee_rejected():
    payload = make_capture(dynamic_fee_nonzero=True)
    with pytest.raises(ClmmCaptureError, match="DYNAMIC_FEE_LAYOUT_NOT_MIRRORED"):
        decode_clmm_capture(payload)


def test_zero_liquidity_and_bad_amounts_rejected():
    capture = decode_clmm_capture(make_capture(liquidity=0))
    with pytest.raises(ClmmCaptureError, match="INSUFFICIENT_ACTIVE_LIQUIDITY"):
        clmm_exact_in_quote(capture, 1, zero_for_one=True)
    capture = decode_clmm_capture(make_capture())
    with pytest.raises(ClmmCaptureError, match="amount_in"):
        clmm_exact_in_quote(capture, 0, zero_for_one=True)


def test_incoherent_sqrt_and_tick_rejected():
    capture = decode_clmm_capture(
        make_capture(sqrt_price_x64=get_sqrt_price_at_tick(5))
    )
    with pytest.raises(ClmmCaptureError, match="incoherent"):
        clmm_exact_in_quote(capture, 1, zero_for_one=True)


def test_unexpected_account_rejected():
    payload = make_capture()
    payload["accounts"].append(
        {
            "address": address(60),
            "value": {
                "data": [base64.b64encode(bytes(64)).decode(), "base64"],
                "owner": CLMM_PROGRAM,
                "executable": False,
                "lamports": 1,
            },
        }
    )
    rehash(payload)
    with pytest.raises(ClmmCaptureError, match="unexpected accounts"):
        decode_clmm_capture(payload)


def test_live_capture_flag_is_rejected():
    payload = make_capture()
    payload["live_capture_authorized"] = True
    with pytest.raises(ClmmCaptureError, match="LIVE_CAPTURE_NOT_AUTHORIZED"):
        decode_clmm_capture(payload)


def test_tick_array_decoder_rejects_wrong_pool():
    from src.providers.raydium_cpmm_native import NativeAccount

    payload = make_capture()
    capture = decode_clmm_capture(payload)
    array_key = tick_array_keys(payload)[0]
    other_pool_key = address(53)
    other_payload = make_capture(pool_key=other_pool_key)
    other_array_key = str(
        Pubkey.find_program_address(
            [
                b"tick_array",
                bytes(Pubkey.from_string(other_pool_key)),
                (0).to_bytes(4, "big"),
            ],
            Pubkey.from_string(CLMM_PROGRAM),
        )[0]
    )
    other_entry = find_account(other_payload, other_array_key)
    account = NativeAccount.from_rpc(array_key, other_entry["value"])
    with pytest.raises(ClmmCaptureError, match="different pool"):
        decode_tick_array(account, capture.pool)
