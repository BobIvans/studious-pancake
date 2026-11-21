"""CLMM bitmap-extension + dynamic-fee completion and DLMM exact-in quote.

Differential vectors are ported from the pinned upstream test suites:
- Raydium CLMM: ``tickarray_bitmap_extension.rs.txt`` unit tests and
  ``pool_fee.rs.txt`` / ``swap.rs.txt`` dynamic-fee tests (Apache-2.0).
- Meteora DLMM: the pinned SDK closure at 1532e540 (fee/bin/math helpers,
  swapQuote loop semantics, token_2022 transfer-fee rules, ISC).

All fixtures are synthetic offline bytes; nothing here is live evidence.
"""

from __future__ import annotations

import base64
import hashlib
import struct

import pytest
from solders.pubkey import Pubkey

from src.providers.meteora_dlmm_native import (
    BASIS_POINT_MAX,
    BIN_ARRAY_BITMAP_SIZE,
    BIN_ARRAY_BITMAP_EXTENSION_LEN,
    FEE_PRECISION,
    METEORA_DLMM_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
    _get_amount_in,
    _get_amount_out,
    _get_excluded_fee_amount,
    _get_included_fee_amount,
    _swap_exact_in_quote_at_bin,
    _token_evidence_for,
    bin_array_index_for_bin_id,
    calculate_transfer_fee_excluded_amount,
    calculate_transfer_fee_included_amount,
    decode_bin_array,
    decode_bin_array_bitmap_extension,
    decode_dlmm_token_mint_evidence,
    decode_lb_pair,
    derive_bin_array_bitmap_extension_pda,
    dlmm_reachable_state,
    dlmm_swap_exact_in_quote,
    find_next_bin_array_index_with_liquidity,
    get_total_fee,
)
from src.providers.raydium_clmm_native import (
    CLMM_DECODER_REVISION,
    RAYDIUM_CLMM_PROGRAM_ID,
    TICK_ARRAY_BITMAP_EXTENSION_LEN,
    ClmmDynamicFeeInfo,
    ClmmTickArray,
    ClmmTickState,
    _compute_swap_step,
    clmm_bitmap_extension_pda,
    clmm_exact_in_quote,
    clmm_tick_array_pda,
    compute_dynamic_fee_rate,
    decode_clmm_bitmap_extension,
    decode_clmm_dynamic_fee_config,
    decode_clmm_dynamic_fee_info,
    decode_clmm_pool_state,
    decode_clmm_tick_array,
    dynamic_fee_update_reference,
    dynamic_fee_update_volatility_accumulator,
    extension_array_initialized,
    extension_next_array_start,
    _extension_bitmap_offset,
    _extension_array_offset_in_bitmap,
    _max_tick_in_bitmap,
    tick_array_start_index,
    tick_spacing_index_from_tick,
)
from src.providers.raydium_cpmm_native import NativeAccount, NativeCaptureError
from tests.meteora_dlmm_fixtures import (
    bin_array_bitmap_extension_bytes,
    bin_array_bytes,
    lb_pair_bytes,
    lb_pair_bytes_v2,
    rpc_account as dlmm_account,
    token_2022_mint_bytes,
)


def derive_bin_array_pda(pair_id: str, index: int) -> str:
    address_key, _ = Pubkey.find_program_address(
        [b"bin_array", bytes(Pubkey.from_string(pair_id)), struct.pack("<q", index)],
        Pubkey.from_string(METEORA_DLMM_PROGRAM_ID),
    )
    return str(address_key)


from tests.native_cpmm_fixtures import address
from tests.raydium_clmm_fixtures import (
    clmm_amm_config_bytes,
    clmm_bitmap_extension_bytes,
    clmm_dynamic_fee_config_bytes,
    clmm_pool_bytes,
    clmm_pool_bytes_v2,
    clmm_tick_array_bytes,
    rpc_account,
)


def _native(entry: dict):
    return NativeAccount.from_rpc(entry["address"], entry)


def _extension(
    pool_id: str,
    *,
    positive=None,
    negative=None,
    positive_bits=None,
    negative_bits=None,
):
    data = clmm_bitmap_extension_bytes(
        pool_id,
        positive_bits=positive or positive_bits,
        negative_bits=negative or negative_bits,
    )
    entry = rpc_account(
        clmm_bitmap_extension_pda(pool_id), RAYDIUM_CLMM_PROGRAM_ID, data
    )
    return decode_clmm_bitmap_extension(_native(entry), expected_pool=pool_id)


def _dlmm_extension(pair_id: str, *, positive_bits=None, negative_bits=None):
    data = bin_array_bitmap_extension_bytes(
        pair_id, positive_bits=positive_bits, negative_bits=negative_bits
    )
    entry = dlmm_account(
        derive_bin_array_bitmap_extension_pda(pair_id),
        METEORA_DLMM_PROGRAM_ID,
        data,
    )
    return decode_bin_array_bitmap_extension(_native(entry), expected_pair=pair_id)


# ---------------------------------------------------------------------------
# Raydium CLMM: extension bitmap differential vectors (Rust unit tests)
# ---------------------------------------------------------------------------


def test_clmm_extension_bitmap_offset_matches_rust_vectors():
    ts = 1
    array_ticks = 60
    # get_bitmap_offset_test (positive side)
    assert _extension_bitmap_offset(ts * array_ticks * 512, ts) == 0
    assert _extension_bitmap_offset(ts * array_ticks * 513, ts) == 0
    assert _extension_bitmap_offset(ts * array_ticks * 1024, ts) == 1
    assert _extension_bitmap_offset(ts * array_ticks * 7393, ts) == 13
    # negative side
    assert _extension_bitmap_offset(-ts * array_ticks * 513, ts) == 0
    assert _extension_bitmap_offset(-ts * array_ticks * 1024, ts) == 0
    assert _extension_bitmap_offset(-ts * array_ticks * 1025, ts) == 1
    assert _extension_bitmap_offset(-ts * array_ticks * 7394, ts) == 13
    with pytest.raises(NativeCaptureError, match="in-pool bitmap boundary"):
        _extension_bitmap_offset(-ts * array_ticks * 512, ts)  # boundary is in-pool
    with pytest.raises(NativeCaptureError, match="outside pinned range"):
        _extension_bitmap_offset(ts * array_ticks * 7394, ts)
    with pytest.raises(NativeCaptureError, match="outside pinned range"):
        _extension_bitmap_offset(-ts * array_ticks * 7395, ts)


def test_clmm_extension_array_offset_matches_flip_vectors():
    ts = 1
    # flip_tick_array_bit_test: start indexes and the bit they flip.
    cases = [
        (ts * 60 * 512, 0, 0),
        (ts * 60 * 513, 0, 1),
        (ts * 60 * 7393, 13, 225),
        (-ts * 60 * 513, 0, 511),
        (-ts * 60 * 514, 0, 510),
        (-ts * 60 * 1024, 0, 0),
        (-ts * 60 * 7394, 13, 286),
    ]
    for start, slot, bit in cases:
        assert _extension_bitmap_offset(start, ts) == slot
        assert _extension_array_offset_in_bitmap(start, ts) == bit
    ts = 3
    for start, slot, bit in [
        (3 * 60 * 512, 0, 0),
        (3 * 60 * 2464, 3, 416),
        (-3 * 60 * 513, 0, 511),
        (-3 * 60 * 2465, 3, 95),
    ]:
        assert _extension_bitmap_offset(start, ts) == slot
        assert _extension_array_offset_in_bitmap(start, ts) == bit


def _ext_from_bits(ts, starts):
    positive = {}
    negative = {}
    for start in starts:
        slot = _extension_bitmap_offset(start, ts)
        bit = _extension_array_offset_in_bitmap(start, ts)
        target = positive if start > 0 else negative
        target.setdefault(slot, set()).add(bit)
    return {"positive": positive, "negative": negative}


def test_clmm_extension_next_initialized_matches_rust_vectors():
    ts = 1
    bits = _ext_from_bits(ts, [ts * 60 * 512, ts * 60 * 1000, ts * 60 * 7393])
    ext = _extension(address(75), positive=bits["positive"], negative=bits["negative"])
    assert extension_next_array_start(ext, ts * 60 * 511, ts, zero_for_one=False) == (
        True,
        ts * 60 * 512,
    )
    assert extension_next_array_start(ext, ts * 60 * 512, ts, zero_for_one=False) == (
        True,
        ts * 60 * 1000,
    )
    assert extension_next_array_start(ext, ts * 60 * 7393, ts, zero_for_one=False) == (
        False,
        ts * 60 * 7394,
    )
    assert extension_next_array_start(ext, ts * 60 * 1001, ts, zero_for_one=True) == (
        True,
        ts * 60 * 1000,
    )
    assert extension_next_array_start(ext, ts * 60 * 1000, ts, zero_for_one=True) == (
        True,
        ts * 60 * 512,
    )
    # zero_for_one from the lowest extension boundary: the pinned search
    # re-derives the bitmap for the previous array, which lies inside the
    # in-pool boundary, and errors (Rust test asserts is_err).
    with pytest.raises(NativeCaptureError, match="in-pool bitmap boundary"):
        extension_next_array_start(ext, ts * 60 * 512, ts, zero_for_one=True)

    # negative side vectors
    ext_neg = _extension(
        address(75),
        **_ext_from_bits(ts, [-ts * 60 * 513, -ts * 60 * 1000, -ts * 60 * 7394]),
    )
    assert extension_next_array_start(
        ext_neg, -ts * 60 * 1001, ts, zero_for_one=False
    ) == (True, -ts * 60 * 1000)
    assert extension_next_array_start(
        ext_neg, -ts * 60 * 1000, ts, zero_for_one=False
    ) == (True, -ts * 60 * 513)
    with pytest.raises(NativeCaptureError, match="in-pool bitmap boundary"):
        extension_next_array_start(ext_neg, -ts * 60 * 513, ts, zero_for_one=False)
    assert extension_next_array_start(
        ext_neg, -ts * 60 * 512, ts, zero_for_one=True
    ) == (True, -ts * 60 * 513)
    assert extension_next_array_start(
        ext_neg, -ts * 60 * 7394, ts, zero_for_one=True
    ) == (False, -ts * 60 * 7395)


def test_clmm_extension_all_bits_initialized_walks_full_range():
    # next_initialized_tick_array_with_all_initialized_bit_test (ts 1/10/60).
    for ts in (1, 10, 60):
        positive = {slot: set(range(512)) for slot in range(14)}
        negative = {slot: set(range(512)) for slot in range(14)}
        ext = _extension(address(75), positive_bits=positive, negative_bits=negative)
        boundary = _max_tick_in_bitmap(ts)
        start = boundary
        count = 0
        while True:
            found, index = extension_next_array_start(
                ext, start, ts, zero_for_one=False
            )
            if not found:
                break
            assert index == start + 60 * ts
            start = index
            count += 1
            assert count < 10000
        start = -boundary
        count = 0
        while True:
            found, index = extension_next_array_start(ext, start, ts, zero_for_one=True)
            if not found:
                break
            assert index == start - 60 * ts
            start = index
            count += 1
            assert count < 10000


def test_clmm_extension_decode_and_binding_matrix():
    scene_pool = address(70)
    data = clmm_bitmap_extension_bytes(scene_pool, positive_bits={0: {1, 2}})
    entry = rpc_account(
        clmm_bitmap_extension_pda(scene_pool), RAYDIUM_CLMM_PROGRAM_ID, data
    )
    ext = decode_clmm_bitmap_extension(_native(entry), expected_pool=scene_pool)
    assert ext.positive_bitmap[0] == 0b110
    assert len(ext.positive_bitmap) == 14 and len(ext.negative_bitmap) == 14
    wrong_pool = rpc_account(
        clmm_bitmap_extension_pda(scene_pool),
        RAYDIUM_CLMM_PROGRAM_ID,
        clmm_bitmap_extension_bytes(address(71), positive_bits={0: {1, 2}}),
    )
    with pytest.raises(NativeCaptureError, match="pool binding mismatch"):
        decode_clmm_bitmap_extension(_native(wrong_pool), expected_pool=address(72))
    wrong_pda = rpc_account(address(73), RAYDIUM_CLMM_PROGRAM_ID, data)
    with pytest.raises(NativeCaptureError, match="PDA mismatch"):
        decode_clmm_bitmap_extension(_native(wrong_pda), expected_pool=scene_pool)
    truncated = bytearray(data[:-1])
    bad = rpc_account(
        clmm_bitmap_extension_pda(scene_pool),
        RAYDIUM_CLMM_PROGRAM_ID,
        bytes(truncated),
    )
    with pytest.raises(NativeCaptureError, match="layout/discriminator"):
        decode_clmm_bitmap_extension(_native(bad), expected_pool=scene_pool)
    with pytest.raises(NativeCaptureError, match="owner, executable or size"):
        decode_clmm_bitmap_extension(
            _native(_mutated_owner(entry)), expected_pool=scene_pool
        )


def _mutated_owner(entry: dict) -> dict:
    mutated = dict(entry)
    mutated["owner"] = address(74)
    return mutated


# ---------------------------------------------------------------------------
# Raydium CLMM: dynamic fee (pool_fee.rs.txt / swap.rs.txt vectors)
# ---------------------------------------------------------------------------


def test_clmm_tick_spacing_index_from_tick_matches_rust_vectors():
    for spacing in (1, 10, 60):
        assert tick_spacing_index_from_tick(0, spacing) == 0
        assert tick_spacing_index_from_tick(spacing, spacing) == 1
        assert tick_spacing_index_from_tick(-spacing, spacing) == -1
    assert tick_spacing_index_from_tick(5, 10) == 0
    assert tick_spacing_index_from_tick(11, 10) == 1
    assert tick_spacing_index_from_tick(-11, 10) == -2
    assert tick_spacing_index_from_tick(-19, 10) == -2
    assert tick_spacing_index_from_tick(-21, 10) == -3
    assert tick_spacing_index_from_tick(121, 60) == 2
    assert tick_spacing_index_from_tick(-121, 60) == -3


def _fee_info(**overrides) -> ClmmDynamicFeeInfo:
    base = dict(
        filter_period=60,
        decay_period=300,
        reduction_factor=5_000,
        dynamic_fee_control=1_000,
        max_volatility_accumulator=100_000,
        tick_spacing_index_reference=0,
        volatility_reference=0,
        volatility_accumulator=0,
        last_update_timestamp=0,
    )
    base.update(overrides)
    return ClmmDynamicFeeInfo(**base)


def test_clmm_dynamic_fee_update_reference_windows():
    info = _fee_info()
    # high-frequency window: no update
    same = dynamic_fee_update_reference(info, 10, 59)
    assert same is info
    # decay window: decayed volatility reference
    decayed = dynamic_fee_update_reference(info, 10, 100)
    assert decayed.tick_spacing_index_reference == 10
    assert decayed.volatility_reference == 0
    assert decayed.last_update_timestamp == 100
    # reset window: volatility reference zeroed
    acc = dynamic_fee_update_volatility_accumulator(info, 4)
    assert acc.volatility_accumulator == 40_000
    reset = dynamic_fee_update_reference(acc, 20, 400)
    assert reset.volatility_reference == 0
    assert reset.tick_spacing_index_reference == 20
    # saturating elapsed (timestamp regression)
    assert dynamic_fee_update_reference(info, 5, 0) is info


def test_clmm_dynamic_fee_accumulator_clamped():
    info = _fee_info(volatility_reference=90_000)
    acc = dynamic_fee_update_volatility_accumulator(info, 50)
    assert acc.volatility_accumulator == 100_000  # clamped to max


def test_clmm_compute_dynamic_fee_rate_matches_rust_vector():
    # swap.rs dynamic_fee_swap_test: control 1000, ts 1, one crossed group
    # (volatility_accumulator = VOLATILITY_ACCUMULATOR_SCALE) yields a small
    # positive rate below 1000.
    info = _fee_info(volatility_accumulator=10_000)
    rate = compute_dynamic_fee_rate(info, 1)
    assert 0 < rate < 1000
    assert rate == 1
    # rate saturates at MAX_FEE_RATE_NUMERATOR: control*crossed^2 >= 1e18
    saturated = _fee_info(volatility_accumulator=100_000)
    assert compute_dynamic_fee_rate(saturated, 10_000) == 100_000


def test_clmm_dynamic_fee_info_decode_and_validation():
    assert decode_clmm_dynamic_fee_info(bytes(80)) is None
    raw = bytearray(80)
    struct.pack_into("<HHH", raw, 0, 60, 300, 5_000)
    struct.pack_into("<II", raw, 6, 1_000, 100_000)
    struct.pack_into("<i", raw, 14, -3)
    struct.pack_into("<II", raw, 18, 7_000, 9_000)
    struct.pack_into("<Q", raw, 26, 1_700_000_000)
    info = decode_clmm_dynamic_fee_info(bytes(raw))
    assert info.filter_period == 60 and info.tick_spacing_index_reference == -3
    assert (
        info.volatility_reference == 7_000
        and info.last_update_timestamp == 1_700_000_000
    )
    padded = bytearray(raw)
    padded[40] = 1
    with pytest.raises(NativeCaptureError, match="padding"):
        decode_clmm_dynamic_fee_info(bytes(padded))
    from src.providers.raydium_clmm_native import validate_dynamic_fee_params

    with pytest.raises(NativeCaptureError, match="decay_period"):
        validate_dynamic_fee_params(_fee_info(filter_period=60, decay_period=60), 1)
    with pytest.raises(NativeCaptureError, match="reduction_factor"):
        validate_dynamic_fee_params(_fee_info(reduction_factor=0), 1)
    with pytest.raises(NativeCaptureError, match="control"):
        validate_dynamic_fee_params(_fee_info(dynamic_fee_control=0), 1)


def test_clmm_dynamic_fee_config_decode():
    data = clmm_dynamic_fee_config_bytes(index=3)
    entry = rpc_account(address(80), RAYDIUM_CLMM_PROGRAM_ID, data)
    config = decode_clmm_dynamic_fee_config(_native(entry))
    assert config.index == 3 and config.filter_period == 60
    assert config.dynamic_fee_control == 1_000
    padded = bytearray(data)
    padded[30] = 9
    bad = rpc_account(address(80), RAYDIUM_CLMM_PROGRAM_ID, bytes(padded))
    with pytest.raises(NativeCaptureError, match="padding"):
        decode_clmm_dynamic_fee_config(_native(bad))


def _dynamic_fee_scene(*, fee_on=0, ts=1):
    dyn_raw = bytearray(80)
    struct.pack_into("<HHH", dyn_raw, 0, 60, 300, 5_000)
    struct.pack_into("<II", dyn_raw, 6, 1_000, 100_000)
    struct.pack_into("<q", dyn_raw, 26, 1_700_000_000)
    pool_bytes, pool_id, _ = clmm_pool_bytes_v2(
        config_address=address(12), dynamic_fee_raw=bytes(dyn_raw), fee_on=fee_on
    )
    config_entry = rpc_account(
        address(12), RAYDIUM_CLMM_PROGRAM_ID, clmm_amm_config_bytes()
    )
    config = decode_clmm_amm_config(_native(config_entry))
    pool_entry = rpc_account(pool_id, RAYDIUM_CLMM_PROGRAM_ID, pool_bytes)
    pool = decode_clmm_pool_state(_native(pool_entry))
    start = tick_array_start_index(pool.tick_current, pool.tick_spacing)
    data = clmm_tick_array_bytes(
        pool_id,
        start,
        initialized={
            30: (1_000_000_000_000, 2_000_000_000_000),
            50: (1_000_000_000_000, 2_000_000_000_000),
        },
    )
    array = decode_clmm_tick_array(
        _native(
            rpc_account(
                clmm_tick_array_pda(pool_id, start), RAYDIUM_CLMM_PROGRAM_ID, data
            )
        ),
        expected_pool=pool_id,
        expected_start=start,
    )
    return pool, config, (array,), pool_id


from src.providers.raydium_clmm_native import decode_clmm_amm_config  # noqa: E402


def test_clmm_dynamic_fee_quote_requires_timestamp_and_matches_config():
    pool, config, arrays, pool_id = _dynamic_fee_scene()
    with pytest.raises(NativeCaptureError, match="requires block timestamp"):
        clmm_exact_in_quote(pool, config, arrays, 10**6, zero_for_one=True)
    mismatched = decode_clmm_dynamic_fee_config(
        _native(
            rpc_account(
                address(81),
                RAYDIUM_CLMM_PROGRAM_ID,
                clmm_dynamic_fee_config_bytes(reduction_factor=7_000),
            )
        )
    )
    with pytest.raises(NativeCaptureError, match="config mismatch"):
        clmm_exact_in_quote(
            pool,
            config,
            arrays,
            10**6,
            zero_for_one=True,
            block_timestamp=1_700_001_000,
            dynamic_fee_config=mismatched,
        )


def test_clmm_dynamic_fee_quote_applies_volatility_fee():
    pool, config, arrays, pool_id = _dynamic_fee_scene()
    # Long-elapsed timestamp: reference resets (decay window passed), so the
    # accumulator starts at zero and the dynamic fee at the active group is 0.
    baseline = clmm_exact_in_quote(
        pool, config, arrays, 10**6, zero_for_one=True, block_timestamp=1_800_000_000
    )
    assert baseline.dynamic_fee_decoded is True
    assert baseline.dynamic_fee_rate_end == 0
    assert baseline.amount_in + baseline.fee_amount == 10**6
    assert baseline.tick_end == 100 and baseline.crossed_ticks == ()
    # fee_on=1 (Token0Only) with zero_for_one: fee still from input.
    pool0, config0, arrays0, _ = _dynamic_fee_scene(fee_on=1)
    q0 = clmm_exact_in_quote(
        pool0, config0, arrays0, 10**6, zero_for_one=True, block_timestamp=1_800_000_000
    )
    assert q0.amount_in + q0.fee_amount == 10**6
    # fee_on=1 with one_for_zero: fee moves to the output side.
    q1 = clmm_exact_in_quote(
        pool0,
        config0,
        arrays0,
        10**6,
        zero_for_one=False,
        block_timestamp=1_800_000_000,
    )
    assert q1.amount_in == 10**6 and q1.fee_amount > 0 and q1.amount_out < q0.amount_out


def test_clmm_quote_crosses_into_bitmap_extension_account():
    # Active tick -30690 sits in in-pool array -30720 (bit 0); the only
    # initialized tick below it (-30750) lives in extension array -30780,
    # so the walk must consult the TickArrayBitmapExtension account.
    pool_bytes, pool_id, _ = clmm_pool_bytes(
        config_address=address(12),
        bitmap_bits=(0,),
        liquidity=10_000_000_000_000,
        tick_current=-30690,
    )
    config_entry = rpc_account(
        address(12), RAYDIUM_CLMM_PROGRAM_ID, clmm_amm_config_bytes()
    )
    config = decode_clmm_amm_config(_native(config_entry))
    pool = decode_clmm_pool_state(
        _native(rpc_account(pool_id, RAYDIUM_CLMM_PROGRAM_ID, pool_bytes))
    )
    L = 10_000_000_000_000
    array_specs = {
        -30720: {},  # active array (in-pool bit 0), no initialized ticks
        -30780: {30: (L, 2 * L)},  # tick -30750 (extension range)
    }
    arrays = []
    for start, layout in array_specs.items():
        data = clmm_tick_array_bytes(pool_id, start, initialized=layout)
        arrays.append(
            decode_clmm_tick_array(
                _native(
                    rpc_account(
                        clmm_tick_array_pda(pool_id, start),
                        RAYDIUM_CLMM_PROGRAM_ID,
                        data,
                    )
                ),
                expected_pool=pool_id,
                expected_start=start,
            )
        )
    ext_data = clmm_bitmap_extension_bytes(
        pool_id, negative_bits={0: {511}}  # array start -30780
    )
    extension = decode_clmm_bitmap_extension(
        _native(
            rpc_account(
                clmm_bitmap_extension_pda(pool_id),
                RAYDIUM_CLMM_PROGRAM_ID,
                ext_data,
            )
        ),
        expected_pool=pool_id,
    )
    extension_array = decode_clmm_tick_array(
        _native(
            rpc_account(
                clmm_tick_array_pda(pool_id, -30780),
                RAYDIUM_CLMM_PROGRAM_ID,
                clmm_tick_array_bytes(pool_id, -30780, initialized={30: (L, 2 * L)}),
            )
        ),
        expected_pool=pool_id,
        expected_start=-30780,
    )
    active_array = decode_clmm_tick_array(
        _native(
            rpc_account(
                clmm_tick_array_pda(pool_id, -30720),
                RAYDIUM_CLMM_PROGRAM_ID,
                clmm_tick_array_bytes(pool_id, -30720),
            )
        ),
        expected_pool=pool_id,
        expected_start=-30720,
    )
    quote = clmm_exact_in_quote(
        pool,
        config,
        (active_array, extension_array),
        10**10,
        zero_for_one=True,
        bitmap_extension=extension,
    )
    assert quote.amount_in + quote.fee_amount == 10**10 and quote.amount_out > 0
    # The input is consumed as a partial step between ticks -30690 and
    # -30750, but only after the walk transitioned into the extension array.
    assert quote.crossed_ticks == () and quote.tick_end == -30690
    assert quote.bitmap_extension_used == extension.address
    # Without the extension account the walk fails closed at the boundary.
    with pytest.raises(NativeCaptureError, match="BITMAP_EXTENSION_REQUIRED"):
        clmm_exact_in_quote(
            pool, config, (active_array, extension_array), 10**10, zero_for_one=True
        )


# ---------------------------------------------------------------------------
# Meteora DLMM: exact-in quote (pinned SDK closure vectors)
# ---------------------------------------------------------------------------


def _dlmm_full_scene(
    *,
    active_id=5,
    bin_step=10,
    bins=None,
    swap_for_y=True,
    current_timestamp=1_800_000_000,
    **pair_kwargs,
):
    pair_bytes, pair_id, mints = lb_pair_bytes_v2(
        active_id=active_id, bin_step=bin_step, **pair_kwargs
    )
    # The SDK's bin-array search consults the LbPair bitmap; mark every
    # supplied default-window array as initialized (bit = index + 512).
    buffer = bytearray(pair_bytes)
    for index in bins or {}:
        bit = index + 512
        if 0 <= bit < 1024:
            word = bit // 64
            current = int.from_bytes(buffer[584 + 8 * word : 592 + 8 * word], "little")
            struct.pack_into("<Q", buffer, 584 + 8 * word, current | (1 << (bit % 64)))
    pair_bytes = bytes(buffer)
    pair = decode_lb_pair(
        _native(dlmm_account(pair_id, METEORA_DLMM_PROGRAM_ID, pair_bytes))
    )
    arrays = []
    for index, layout in (bins or {}).items():
        data = bin_array_bytes(pair_id, index, bins=layout)
        arrays.append(
            decode_bin_array(
                _native(
                    dlmm_account(
                        derive_bin_array_pda(pair_id, index),
                        METEORA_DLMM_PROGRAM_ID,
                        data,
                    )
                ),
                expected_pair=pair_id,
            )
        )
    return pair, tuple(arrays), pair_id, mints


def _q64_price(bin_id: int, bin_step: int = 10) -> int:
    # Exact-enough synthetic price: (1 + binStep/10^4)^binId * 2^64, rounded.
    factor = (10_000 + bin_step) / 10_000
    price = round((factor**bin_id) * (1 << 64))
    return price


def test_dlmm_extended_lb_pair_fields_decode():
    pair, _, _, _ = _dlmm_full_scene(
        filter_period=45,
        decay_period=600,
        reduction_factor=6_000,
        protocol_share=2_500,
        function_type=1,
        collect_fee_mode=1,
        volatility_reference=1_500,
        index_reference=3,
        variable_last_update_timestamp=1_700_000_000,
    )
    assert pair.filter_period == 45 and pair.decay_period == 600
    assert pair.reduction_factor == 6_000 and pair.protocol_share == 2_500
    assert pair.function_type_name == "LiquidityMining"
    assert pair.collect_fee_mode_name == "OnlyY"
    assert pair.volatility_reference == 1_500 and pair.index_reference == 3
    assert pair.variable_last_update_timestamp == 1_700_000_000


def test_dlmm_bin_array_bitmap_extension_decode_and_pda():
    pair, _, pair_id, _ = _dlmm_full_scene()
    ext = _dlmm_extension(pair_id, negative_bits={0: {511}})
    assert ext.lb_pair == pair_id
    assert ext.negative_bitmap[0] >> 511 & 1 == 1
    wrong_pair = dlmm_account(
        derive_bin_array_bitmap_extension_pda(pair_id),
        METEORA_DLMM_PROGRAM_ID,
        bin_array_bitmap_extension_bytes(address(90), negative_bits={0: {511}}),
    )
    with pytest.raises(NativeCaptureError, match="pair binding mismatch"):
        decode_bin_array_bitmap_extension(_native(wrong_pair), expected_pair=pair_id)
    wrong_pda = dlmm_account(
        address(91),
        METEORA_DLMM_PROGRAM_ID,
        bin_array_bitmap_extension_bytes(pair_id, negative_bits={0: {511}}),
    )
    with pytest.raises(NativeCaptureError, match="PDA mismatch"):
        decode_bin_array_bitmap_extension(_native(wrong_pda), expected_pair=pair_id)


def test_dlmm_fee_helpers_match_pinned_laws():
    pair, _, _, _ = _dlmm_full_scene()
    # getBaseFee: base_factor(500) * bin_step(10) * 10 * 10^power(1) = 500_000
    assert get_total_fee(pair, 0) == 500_000  # 500*10*10*10^1
    # variable fee: control * (volAcc * binStep)^2 / 1e11 with ceiling
    pair_v = pair
    from src.providers.meteora_dlmm_native import get_variable_fee

    assert get_variable_fee(pair_v, 0) == 0
    acc = 1_000
    # (1000*10)^2 = 1e8; 5000*1e8 = 5e11; (5e11 + 99999999999)//1e11 = 5
    assert get_variable_fee(pair_v, acc) == 5
    # total caps at MAX_FEE_RATE when base alone exceeds it
    from dataclasses import replace as _replace

    huge = _replace(pair_v, bin_step=100_000)
    assert get_total_fee(huge, 0) == 100_000_000


def test_dlmm_amount_rounding_matches_pinned_laws():
    price = _q64_price(5)
    out = _get_amount_out(0, 10_000, price, swap_for_y=True)
    assert out == (10_000 * price) >> 64  # mulShr, Rounding.Down
    in_back = _get_amount_in(out, price, swap_for_y=True)
    assert in_back == (out * (1 << 64) + price - 1) // price  # shlDiv, Up
    # swapForY=False: Y in -> X out via price division (Rounding.Down)
    out_x = _get_amount_out(0, price, price, swap_for_y=False)
    assert out_x == (price * (1 << 64)) // price
    in_x = _get_amount_in(out_x, price, swap_for_y=False)
    assert in_x == (out_x * price + (1 << 64) - 1) // (1 << 64)


def test_dlmm_fee_splitting_matches_pinned_laws():
    # getExcludedFeeAmount / getIncludedFeeAmount round-trip identity.
    fee_numerator = 50_000
    amount = 10**9
    excluded, fee = _get_excluded_fee_amount(amount, fee_numerator)
    assert excluded + fee == amount
    included, fee2 = _get_included_fee_amount(excluded, fee_numerator)
    assert included == amount and fee2 == fee
    # splitFee: protocol share 2000 of the mm fee.
    pair, _, _, _ = _dlmm_full_scene(protocol_share=2_000)
    from src.providers.meteora_dlmm_native import _split_fee

    user_fee, protocol_fee = _split_fee(1_000, pair.protocol_share, 1_000)
    assert user_fee + protocol_fee == 1_000
    assert protocol_fee == 200


def test_dlmm_swap_exact_in_quote_positive_swap_for_y():
    L = 1_000_000
    pair, arrays, pair_id, _ = _dlmm_full_scene(
        bins={0: {5: (700, L, _q64_price(5), 1), 4: (700, 2 * L, _q64_price(4), 1)}}
    )
    quote = dlmm_swap_exact_in_quote(
        pair,
        arrays,
        10_000,
        swap_for_y=True,
        clock_epoch=700,
        current_timestamp=1_800_000_000,
    )
    # InputOnly fee mode: fee taken from input; full input consumed.
    assert quote.fee_on_input is True
    assert quote.consumed_in_amount == 10_000
    assert quote.partial_fill is False
    assert quote.fee > 0 and quote.out_amount > 0
    # fee = ceil(in * base(50_000) / FEE_PRECISION) with vol_acc 0 at active bin.
    fee_total = (10_000 * 500_000 + FEE_PRECISION - 1) // FEE_PRECISION
    excluded = 10_000 - fee_total
    expected_out = (excluded * _q64_price(5)) >> 64
    assert quote.out_amount == expected_out
    assert quote.bins_used == (5,)
    assert quote.bin_arrays_used == (arrays[0].address,)
    assert quote.end_bin_id == 5
    assert quote.end_price_numerator == (10_000 + 10) ** 5
    assert quote.end_price_denominator == 10_000**5
    assert quote.min_out_amount == quote.out_amount  # zero slippage guard
    # splitFee with total == mm amount: mm fee equals the whole trade fee.
    mm_fee = (fee_total * 10_000 + 10_000 - 1) // 10_000
    assert quote.protocol_fee == (mm_fee * pair.protocol_share) // BASIS_POINT_MAX


def test_dlmm_swap_exact_in_quote_multi_bin_and_direction():
    L = 10_000_000
    pair, arrays, _, _ = _dlmm_full_scene(
        bins={
            0: {
                5: (10_000_000, L, _q64_price(5), 1),
                4: (10_000_000, L, _q64_price(4), 1),
                3: (10_000_000, L, _q64_price(3), 1),
            }
        }
    )
    small = dlmm_swap_exact_in_quote(
        pair,
        arrays,
        1_000,
        swap_for_y=True,
        clock_epoch=700,
        current_timestamp=1_800_000_000,
    )
    big = dlmm_swap_exact_in_quote(
        pair,
        arrays,
        25_000_000,
        swap_for_y=True,
        clock_epoch=700,
        current_timestamp=1_800_000_000,
    )
    assert big.out_amount > small.out_amount
    assert len(big.bins_used) >= 2 and big.end_bin_id < small.end_bin_id
    assert big.consumed_in_amount == 25_000_000
    # Reverse direction: Y -> X fills amount_x and walks upward.
    up_pair, up_arrays, _, _ = _dlmm_full_scene(
        bins={
            0: {
                5: (10_000_000, L, _q64_price(5), 1),
                6: (10_000_000, L, _q64_price(6), 1),
                7: (10_000_000, L, _q64_price(7), 1),
            }
        }
    )
    reverse = dlmm_swap_exact_in_quote(
        up_pair,
        up_arrays,
        20_000_000,
        swap_for_y=False,
        clock_epoch=700,
        current_timestamp=1_800_000_000,
    )
    assert reverse.consumed_in_amount == 20_000_000
    assert reverse.out_amount > 0 and reverse.end_bin_id >= 5
    assert reverse.fee_on_input is True  # InputOnly mode


def test_dlmm_swap_quote_exhaustion_and_limit_order_rejections():
    pair, arrays, _, _ = _dlmm_full_scene(bins={0: {5: (0, 1_000, _q64_price(5), 1)}})
    with pytest.raises(NativeCaptureError, match="INSUFFICIENT_LIQUIDITY"):
        dlmm_swap_exact_in_quote(
            pair,
            arrays,
            10**9,
            swap_for_y=True,
            clock_epoch=700,
            current_timestamp=1_800_000_000,
        )
    partial = dlmm_swap_exact_in_quote(
        pair,
        arrays,
        10**9,
        swap_for_y=True,
        clock_epoch=700,
        current_timestamp=1_800_000_000,
        is_partial_fill=True,
    )
    assert partial.partial_fill is True
    assert partial.consumed_input_matches_request is False
    assert partial.consumed_in_amount < 10**9
    lo_pair, lo_arrays, _, _ = _dlmm_full_scene(function_type=2)
    with pytest.raises(NativeCaptureError, match="LIMIT_ORDER_PAIR_REJECTED"):
        dlmm_swap_exact_in_quote(
            lo_pair,
            lo_arrays,
            1_000,
            swap_for_y=True,
            clock_epoch=700,
            current_timestamp=1_800_000_000,
        )
    undetermined, u_arrays, _, _ = _dlmm_full_scene(function_type=0)
    with pytest.raises(NativeCaptureError, match="LIMIT_ORDER_PAIR_REJECTED"):
        dlmm_swap_exact_in_quote(
            undetermined,
            u_arrays,
            1_000,
            swap_for_y=True,
            clock_epoch=700,
            current_timestamp=1_800_000_000,
        )


def test_dlmm_swap_quote_bounded_traversal_and_bad_inputs():
    pair, arrays, _, _ = _dlmm_full_scene(bins={0: {5: (700, 1_000, _q64_price(5), 1)}})
    with pytest.raises(NativeCaptureError, match="amount out of u64 range"):
        dlmm_swap_exact_in_quote(
            pair, arrays, 0, swap_for_y=True, clock_epoch=700, current_timestamp=1
        )
    with pytest.raises(NativeCaptureError, match="slippage"):
        dlmm_swap_exact_in_quote(
            pair,
            arrays,
            10,
            swap_for_y=True,
            clock_epoch=700,
            current_timestamp=1,
            allowed_slippage_bps=BASIS_POINT_MAX + 1,
        )
    disabled_pair, d_arrays, _, _ = _dlmm_full_scene(status=1)
    with pytest.raises(NativeCaptureError, match="disabled"):
        dlmm_swap_exact_in_quote(
            disabled_pair,
            d_arrays,
            10,
            swap_for_y=True,
            clock_epoch=700,
            current_timestamp=1,
        )


def test_dlmm_walk_uses_bitmap_extension_across_default_window():
    L = 5_000_000
    # Active bin 5, array 0; single bin of liquidity far below the default
    # window: array index -600 (bin id -42000 - within negative extension).
    lower = -600 * 70
    far_bin_id = lower + 35
    pair, arrays, pair_id, _ = _dlmm_full_scene(
        bins={
            0: {5: (700, 1_000, _q64_price(5), 1)},
            -600: {35: (700, L, _q64_price(far_bin_id), 1)},
        },
        min_bin_id=-70000,
        max_bin_id=70000,
    )
    # Pinned offsets for negative index i: shifted = -(i+1);
    # slot = shifted // 512 - 1, bit = shifted % 512.
    shifted = 600 - 1
    negative_slot, negative_bit = (
        shifted // BIN_ARRAY_BITMAP_SIZE - 1,
        shifted % BIN_ARRAY_BITMAP_SIZE,
    )
    ext = _dlmm_extension(pair_id, negative_bits={negative_slot: {negative_bit}})
    # The default (internal) bitmap must mark array 0 as initialized.
    pair_buf = bytearray(
        lb_pair_bytes_v2(active_id=5, min_bin_id=-70000, max_bin_id=70000)[0]
    )
    struct.pack_into("<Q", pair_buf, 584 + 8 * 8, 1 << 0)  # bit 512 -> array 0
    pair = decode_lb_pair(
        _native(dlmm_account(pair_id, METEORA_DLMM_PROGRAM_ID, bytes(pair_buf)))
    )
    with pytest.raises(NativeCaptureError, match="INSUFFICIENT_LIQUIDITY"):
        dlmm_swap_exact_in_quote(
            pair,
            arrays,
            10**7,
            swap_for_y=True,
            clock_epoch=700,
            current_timestamp=1_800_000_000,
        )
    quote = dlmm_swap_exact_in_quote(
        pair,
        arrays,
        10**7,
        swap_for_y=True,
        clock_epoch=700,
        current_timestamp=1_800_000_000,
        bin_array_bitmap_extension=ext,
    )
    assert quote.consumed_in_amount == 10**7
    assert far_bin_id in quote.bins_used


def test_dlmm_token_2022_transfer_fee_and_hook_evidence():
    data, mint = token_2022_mint_bytes(
        transfer_fee_epoch=600, transfer_fee_bps=200, transfer_fee_maximum=1_000
    )
    entry = dlmm_account(mint, TOKEN_2022_PROGRAM_ID, data)
    evidence = decode_dlmm_token_mint_evidence(_native(entry))
    assert evidence.transfer_fee_basis_points == 200
    # excluded amount loses floor(in * 200 / 10000)
    assert calculate_transfer_fee_excluded_amount(10_000, evidence, 700) == 10_000 - 200
    # included amount: ceil inverse via calculatePreFeeAmount
    included = calculate_transfer_fee_included_amount(10_000, evidence, 700)
    # Pinned ceiling inverse: preFee = ceil(10000*10000/9800) = 10205.
    assert included == 10_205
    # epoch ahead of clock is rejected
    with pytest.raises(NativeCaptureError, match="EPOCH_AHEAD_OF_CLOCK"):
        calculate_transfer_fee_excluded_amount(10_000, evidence, 599)
    # hook is rejected via the quote-path gate
    hook_data, hook_mint = token_2022_mint_bytes(
        transfer_hook_program=address(92),
        transfer_fee_epoch=600,
        transfer_fee_bps=0,
        transfer_fee_maximum=0,
    )
    hook_evidence = decode_dlmm_token_mint_evidence(
        _native(dlmm_account(hook_mint, TOKEN_2022_PROGRAM_ID, hook_data))
    )
    with pytest.raises(NativeCaptureError, match="TRANSFER_HOOK_UNRESOLVED"):
        _token_evidence_for(hook_mint, TOKEN_2022_PROGRAM_ID, hook_evidence)
    unknown_data, unknown_mint = token_2022_mint_bytes(unknown_tag=77)
    unknown_evidence = decode_dlmm_token_mint_evidence(
        _native(dlmm_account(unknown_mint, TOKEN_2022_PROGRAM_ID, unknown_data))
    )
    with pytest.raises(NativeCaptureError, match="UNKNOWN_EXTENSION"):
        _token_evidence_for(unknown_mint, TOKEN_2022_PROGRAM_ID, unknown_evidence)
    # missing evidence fails closed
    with pytest.raises(NativeCaptureError, match="TRANSFER_FEE_UNRESOLVED"):
        _token_evidence_for(mint, TOKEN_2022_PROGRAM_ID, None)


def test_dlmm_swap_quote_per_bin_vector():
    # Hand-computed vector of swapExactInQuoteAtBin (feeOnInput, partial bin).
    price = _q64_price(5)
    from src.providers.meteora_dlmm_native import DlmmBin

    pair, _, _, _ = _dlmm_full_scene()
    bin_state = DlmmBin(
        bin_id=5, amount_x=700, amount_y=1_000_000, price=price, liquidity_supply=1
    )
    amount_in = 10_000
    fee_numerator = get_total_fee(pair, 0)
    fee_total = (amount_in * fee_numerator + FEE_PRECISION - 1) // FEE_PRECISION
    fee = (amount_in * fee_numerator + FEE_PRECISION - 1) // FEE_PRECISION
    excluded_in = amount_in - fee
    max_in = _get_amount_in(1_000_000, price, swap_for_y=True)
    assert excluded_in < max_in  # partial bin fill
    amount_in_bin, amount_out_bin, fee_bin, protocol_bin = _swap_exact_in_quote_at_bin(
        bin_state, pair, 0, amount_in, swap_for_y=True, fee_on_input=True
    )
    expected_out = (excluded_in * price) >> 64
    assert amount_in_bin == amount_in
    assert amount_out_bin == expected_out
    # _swap_exact_in_quote_at_bin returns the user fee (after splitFee).
    assert fee_bin == fee_total - protocol_bin
    assert protocol_bin == (fee_total * pair.protocol_share) // BASIS_POINT_MAX
    # Full-bin fill: input beyond capacity caps at maxAmountOut.
    huge = 10**18
    a_in, a_out, fee_h, _ = _swap_exact_in_quote_at_bin(
        bin_state, pair, 0, huge, swap_for_y=True, fee_on_input=True
    )
    assert a_out == 1_000_000
    # Pinned: the returned input is the fee-included amount of maxAmountIn.
    assert a_in == _get_included_fee_amount(max_in, fee_numerator)[0]
