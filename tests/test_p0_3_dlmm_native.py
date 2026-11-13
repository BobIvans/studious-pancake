"""P0-3 Meteora DLMM native decoder + exact-in bin-walk math: differential fixtures.

Positive expectations are hand-derived in this file from the pinned vendor
fragments (IDL layouts; SDK swapQuote loop, getFeeMode, updateReference/
updateVolatilityAccumulator, calculateFeeInfo, binArray.ts helpers, and the
syncWithMarketPrice price-scale fragment) written out independently of the
provider module. The per-bin amount math, fee rounding and variable-fee
formula are DOCUMENTED (dlmm-sdk math module not mirrored) and every quote
carries ``math_provenance``. Zero network, no signer.
"""

from __future__ import annotations

import base64

import pytest
from solders.pubkey import Pubkey

from tests.native_cpmm_fixtures import rehash
from tests.p0_3_fixtures import (
    BLOCK_TIME,
    DLMM_PROGRAM,
    SLOT,
    address,
    build_dlmm_accounts,
    build_dlmm_bitmap_extension,
    dlmm_capture,
)
from src.providers.meteora_dlmm_native import (
    DlmmCaptureError,
    bin_id_to_bin_array_index,
    decode_bin_array,
    decode_dlmm_capture,
    dlmm_exact_in_quote,
    variable_fee_rate,
)
from src.providers.raydium_cpmm_native import NativeAccount

pytestmark = pytest.mark.unit

# Stored bin prices: Y-per-X fraction scaled by 2**64 [PINNED scale fragment];
# bin_step = 10 -> one bin is factor 1.001 = 1001/1000.
PX0 = 1 << 64
PXm1 = ((1 << 64) * 1000) // 1001
PXm2 = ((1 << 64) * 1000 * 1000) // (1001 * 1001)
PX1 = ((1 << 64) * 1001) // 1000

MINT_X = address(3)
MINT_Y = address(4)
RESERVE_X = address(22)
RESERVE_Y = address(23)
PAIR = address(51)

BASE_BINS = {
    0: (10**9, 0, PX0),
    -1: (0, 10**9, PXm1),
    -2: (0, 2 * 10**9, PXm2),
    1: (10**9, 0, PX1),
}
BASE_BITMAP = [511, 512]  # bin arrays -1 and 0 initialized
BASE_ARRAYS = [-1, 0]


def make_capture(**overrides) -> dict:
    params = dict(
        pair_key=PAIR,
        mint_x=MINT_X,
        mint_y=MINT_Y,
        reserve_x=RESERVE_X,
        reserve_y=RESERVE_Y,
        bins=BASE_BINS,
        bitmap_bits=BASE_BITMAP,
        include_bin_array_indexes=BASE_ARRAYS,
    )
    params.update(overrides)
    accounts = build_dlmm_accounts(**params)
    array_keys = {
        index: str(
            Pubkey.find_program_address(
                [
                    b"bin_array",
                    bytes(Pubkey.from_string(PAIR)),
                    (index & ((1 << 64) - 1)).to_bytes(8, "little"),
                ],
                Pubkey.from_string(DLMM_PROGRAM),
            )[0]
        )
        for index in params["include_bin_array_indexes"]
    }
    bin_array_ids = [array_keys[index] for index in params["include_bin_array_indexes"]]
    return dlmm_capture(accounts, PAIR, bin_array_ids)


def find_account(payload: dict, key: str) -> dict:
    return next(e for e in payload["accounts"] if e["address"] == key)


def mutate(payload: dict, key: str, change) -> None:
    entry = find_account(payload, key)
    data = bytearray(base64.b64decode(entry["value"]["data"][0]))
    change(data)
    entry["value"]["data"][0] = base64.b64encode(data).decode()
    rehash(payload)


def array_key(index: int) -> str:
    return str(
        Pubkey.find_program_address(
            [
                b"bin_array",
                bytes(Pubkey.from_string(PAIR)),
                (index & ((1 << 64) - 1)).to_bytes(8, "little"),
            ],
            Pubkey.from_string(DLMM_PROGRAM),
        )[0]
    )


def _div_ceil(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def _gross_for_net(net: int, fee_rate: int) -> int:
    """[DOCUMENTED] minimal gross g with g - ceil(g*rate/1e9) >= net."""
    gross = _div_ceil(net * 1_000_000_000, 1_000_000_000 - fee_rate)
    while gross - _div_ceil(gross * fee_rate, 1_000_000_000) < net:
        gross += 1
    while gross - 1 - _div_ceil((gross - 1) * fee_rate, 1_000_000_000) >= net:
        gross -= 1
    return gross


# ---------------------------------------------------------------------------
# Positive differential fixtures (hand-verified)
# ---------------------------------------------------------------------------


def test_capture_decode_and_identity():
    capture = decode_dlmm_capture(make_capture())
    assert capture.pair.address == PAIR
    assert capture.pair.active_id == 0
    assert capture.pair.bin_step == 10
    assert capture.pair.parameters.collect_fee_mode == 0
    assert capture.pair.parameters.protocol_share == 1000
    assert capture.mints == (MINT_X, MINT_Y)
    assert len(capture.bin_arrays) == 2
    assert capture.bitmap_extension is None
    assert capture.slot == SLOT
    assert capture.block_time == BLOCK_TIME


def test_bin_array_index_helpers():
    assert bin_id_to_bin_array_index(0) == 0
    assert bin_id_to_bin_array_index(69) == 0
    assert bin_id_to_bin_array_index(70) == 1
    assert bin_id_to_bin_array_index(-1) == -1
    assert bin_id_to_bin_array_index(-70) == -1
    assert bin_id_to_bin_array_index(-71) == -2


def test_x_for_y_single_bin_partial_hand_verified():
    capture = decode_dlmm_capture(make_capture())
    amount_in = 500_000_000
    quote = dlmm_exact_in_quote(capture, amount_in, swap_for_y=True)
    fee = _div_ceil(amount_in * 2500, 1_000_000_000)  # exactly 1250
    net = amount_in - fee
    out = (net * PXm1) >> 64
    assert quote.amount_out == out
    assert quote.fee == 1250
    assert quote.protocol_fee == 125
    assert quote.lp_fee == 1125
    assert quote.input_left == 0
    assert quote.bins_used == (-1,)  # active bin 0 holds no Y and is skipped
    assert quote.end_bin_id == -1
    assert quote.fee_on_input is True
    assert quote.variable_fee_applied is False
    assert quote.bin_arrays_used == (array_key(0), array_key(-1))
    assert quote.math_provenance[0].startswith("PINNED:")


def test_x_for_y_drain_and_multi_bin_hand_verified():
    capture = decode_dlmm_capture(make_capture())
    amount_in = 3_000_000_000
    quote = dlmm_exact_in_quote(capture, amount_in, swap_for_y=True)
    # Bin -1 fully drains: fee is charged on the consumed gross.
    drain_net1 = _div_ceil(10**9 << 64, PXm1)
    assert 2_999_992_500 >= drain_net1  # pre-condition for the drain
    gross1 = _gross_for_net(drain_net1, 2500)
    fee1 = gross1 - drain_net1
    remaining2 = amount_in - gross1
    fee2 = _div_ceil(remaining2 * 2500, 1_000_000_000)
    net2 = remaining2 - fee2
    out2 = (net2 * PXm2) >> 64
    drain_net2 = _div_ceil(2 * 10**9 << 64, PXm2)
    assert net2 < drain_net2  # second bin stays partial
    assert quote.amount_out == 10**9 + out2
    assert quote.fee == fee1 + fee2
    # protocol fee floors per bin (the program accounts it per swap step)
    assert quote.protocol_fee == fee1 * 1000 // 10000 + fee2 * 1000 // 10000
    assert quote.bins_used == (-1, -2)
    assert quote.end_bin_id == -2


def test_y_for_x_walk_up_hand_verified():
    capture = decode_dlmm_capture(make_capture())
    amount_in = 400_000_000
    quote = dlmm_exact_in_quote(capture, amount_in, swap_for_y=False)
    fee = _div_ceil(amount_in * 2500, 1_000_000_000)  # 1000
    net = amount_in - fee
    out = (net << 64) // PX0  # PX0 == 2**64 -> out == net
    assert quote.amount_out == out == 399_999_000
    assert quote.fee == 1000
    assert quote.bins_used == (0,)
    assert quote.end_bin_id == 0
    assert quote.bin_arrays_used == (array_key(0),)
    assert quote.fee_on_input is True


def test_only_y_collect_fee_mode_fee_from_output_hand_verified():
    capture = decode_dlmm_capture(make_capture(collect_fee_mode=1))
    amount_in = 500_000_000
    quote = dlmm_exact_in_quote(capture, amount_in, swap_for_y=True)
    gross_out = (amount_in * PXm1) >> 64
    assert gross_out < 10**9  # partial bin
    fee = _div_ceil(gross_out * 2500, 1_000_000_000)
    assert quote.fee_on_input is False
    assert quote.amount_out == gross_out - fee
    assert quote.fee == fee
    assert quote.input_left == 0


def test_bitmap_extension_walk_across_default_boundary():
    extension_key, extension_account = build_dlmm_bitmap_extension(
        PAIR, positive_bits=[599, 600], negative_bits=[]
    )
    bins = {
        42000: (0, 5 * 10**8, PX0),
        41999: (0, 5 * 10**8, PX0),
    }
    params = dict(
        pair_key=PAIR,
        mint_x=MINT_X,
        mint_y=MINT_Y,
        reserve_x=RESERVE_X,
        reserve_y=RESERVE_Y,
        bins=bins,
        bitmap_bits=[],
        include_bin_array_indexes=[599, 600],
        active_id=42000,
        min_bin_id=40000,
        max_bin_id=45000,
    )
    accounts = build_dlmm_accounts(**params)
    accounts[extension_key] = extension_account
    payload = dlmm_capture(
        accounts,
        PAIR,
        [array_key(599), array_key(600)],
        extension_id=extension_key,
    )
    capture = decode_dlmm_capture(payload)
    assert capture.bitmap_extension is not None
    amount_in = 7 * 10**8
    quote = dlmm_exact_in_quote(capture, amount_in, swap_for_y=True)
    drain_net = _div_ceil(5 * 10**8 << 64, PX0)  # == 5e8 for PX0
    gross1 = _gross_for_net(drain_net, 2500)
    fee1 = gross1 - drain_net
    remaining2 = amount_in - gross1
    fee2 = _div_ceil(remaining2 * 2500, 1_000_000_000)
    net2 = remaining2 - fee2
    assert quote.bins_used == (42000, 41999)
    assert quote.amount_out == 5 * 10**8 + net2
    assert quote.fee == fee1 + fee2
    assert len(quote.bin_arrays_used) == 2


def test_variable_fee_documented_policy_is_explicit():
    payload = make_capture(variable_fee_control=500)
    capture = decode_dlmm_capture(payload)
    with pytest.raises(DlmmCaptureError, match="VARIABLE_FEE_FORMULA_NOT_PINNED"):
        dlmm_exact_in_quote(capture, 500_000_000, swap_for_y=True)
    quote = dlmm_exact_in_quote(
        capture, 500_000_000, swap_for_y=True, variable_fee_policy="documented"
    )
    # va after the pinned update: |index_reference(0) - (-1)| * 10000 = 10000.
    assert variable_fee_rate(capture.pair.parameters, 10000, 10) == 50
    fee = _div_ceil(500_000_000 * (2500 + 50), 1_000_000_000)  # 1275
    net = 500_000_000 - fee
    out = (net * PXm1) >> 64
    assert quote.fee == fee
    assert quote.amount_out == out
    assert quote.variable_fee_applied is True


# ---------------------------------------------------------------------------
# Negative fixtures (fail-closed)
# ---------------------------------------------------------------------------


def test_wrong_program_owner_rejected():
    payload = make_capture()
    find_account(payload, PAIR)["value"]["owner"] = address(1)
    rehash(payload)
    with pytest.raises(DlmmCaptureError, match="owner"):
        decode_dlmm_capture(payload)


def test_unknown_discriminator_rejected():
    payload = make_capture()

    def flip(data):
        data[0] ^= 0xFF

    mutate(payload, PAIR, flip)
    with pytest.raises(DlmmCaptureError, match="LbPair layout"):
        decode_dlmm_capture(payload)


def test_truncated_bin_array_rejected():
    payload = make_capture()
    entry = find_account(payload, array_key(-1))
    data = base64.b64decode(entry["value"]["data"][0])
    entry["value"]["data"][0] = base64.b64encode(data[:-1]).decode()
    rehash(payload)
    with pytest.raises(DlmmCaptureError, match="BinArray layout"):
        decode_dlmm_capture(payload)


def test_disabled_pair_rejected():
    payload = make_capture(status=1)
    with pytest.raises(DlmmCaptureError, match="disabled"):
        decode_dlmm_capture(payload)


def test_token_2022_flag_rejected():
    payload = make_capture(token_flags=1)
    with pytest.raises(DlmmCaptureError, match="UNSUPPORTED_TOKEN_PROGRAM"):
        decode_dlmm_capture(payload)


def test_limit_order_pool_rejected():
    payload = make_capture(function_type=2)
    with pytest.raises(DlmmCaptureError, match="LIMIT_ORDER_POOL_NOT_MIRRORED"):
        decode_dlmm_capture(payload)


def test_limit_order_state_rejected():
    payload = make_capture()

    def add_limit_orders(data):
        slot = 69  # bin -1 inside array -1 (reversed layout)
        base = 56 + slot * 144
        data[base + 48 : base + 56] = (12345).to_bytes(8, "little")

    mutate(payload, array_key(-1), add_limit_orders)
    with pytest.raises(DlmmCaptureError, match="LIMIT_ORDER_STATE_PRESENT"):
        decode_dlmm_capture(payload)


def test_missing_bin_array_is_fail_closed():
    # Bitmap marks array -1 but its account is not in the coherent capture;
    # decoding stays coherent and the walk fails closed when it needs it.
    payload = make_capture(include_bin_array_indexes=[0])
    capture = decode_dlmm_capture(payload)
    with pytest.raises(DlmmCaptureError, match="MISSING_BIN_ARRAY"):
        dlmm_exact_in_quote(capture, 500_000_000, swap_for_y=True)


def test_missing_bitmap_extension_is_fail_closed():
    payload = make_capture(
        active_id=42000,
        min_bin_id=40000,
        max_bin_id=45000,
    )
    capture = decode_dlmm_capture(payload)
    with pytest.raises(DlmmCaptureError, match="MISSING_BIN_ARRAY_BITMAP_EXTENSION"):
        dlmm_exact_in_quote(capture, 1, swap_for_y=True)


def test_stale_clock_slot_rejected():
    payload = make_capture()
    payload["slot"] = SLOT + 1
    payload["block"]["parentSlot"] = SLOT
    rehash(payload)
    with pytest.raises(DlmmCaptureError, match="clock slot mismatch"):
        decode_dlmm_capture(payload)


def test_pre_activation_pair_rejected():
    payload = make_capture(activation_point=200)
    with pytest.raises(DlmmCaptureError, match="PRE_ACTIVATION"):
        decode_dlmm_capture(payload)


def test_insufficient_liquidity_for_direction():
    payload = make_capture(
        bins={0: (10**9, 0, PX0)},
        bitmap_bits=[512],
        include_bin_array_indexes=[0],
    )
    capture = decode_dlmm_capture(payload)
    with pytest.raises(DlmmCaptureError, match="INSUFFICIENT_LIQUIDITY"):
        dlmm_exact_in_quote(capture, 500_000_000, swap_for_y=True)


def test_reserve_coherence_violation_rejected():
    payload = make_capture(reserve_y_amount=5)
    with pytest.raises(DlmmCaptureError, match="reserve balances"):
        decode_dlmm_capture(payload)


def test_duplicate_bin_array_accounts_rejected():
    payload = make_capture()
    payload["bin_array_ids"].append(payload["bin_array_ids"][0])
    with pytest.raises(DlmmCaptureError, match="duplicate bin array index"):
        decode_dlmm_capture(payload)


def test_live_capture_flag_is_rejected():
    payload = make_capture()
    payload["live_capture_authorized"] = True
    with pytest.raises(DlmmCaptureError, match="LIVE_CAPTURE_NOT_AUTHORIZED"):
        decode_dlmm_capture(payload)


def test_bin_array_decoder_binds_to_pair():
    payload = make_capture()
    capture = decode_dlmm_capture(payload)
    other_pair_key = address(54)
    other_payload = make_capture(pair_key=other_pair_key)
    other_array = str(
        Pubkey.find_program_address(
            [
                b"bin_array",
                bytes(Pubkey.from_string(other_pair_key)),
                ((-1) & ((1 << 64) - 1)).to_bytes(8, "little"),
            ],
            Pubkey.from_string(DLMM_PROGRAM),
        )[0]
    )
    entry = find_account(other_payload, other_array)
    account = NativeAccount.from_rpc(array_key(-1), entry["value"])
    with pytest.raises(DlmmCaptureError, match="different lb pair"):
        decode_bin_array(account, capture.pair)
