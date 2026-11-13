"""P0-3 exact direct-state decoders: Raydium CLMM + Meteora DLMM.

Positive and negative fixture decoding, vendored differential vectors for the
tick math, pinned swap-step identities, multi-tick traversal, and the honest
DLMM capability boundary (state only; amount-specific quote fails closed).
"""

import base64
import struct

import pytest
from solders.pubkey import Pubkey

from src.providers.meteora_dlmm_native import (
    METEORA_DLMM_PROGRAM_ID,
    base_fee_rate,
    bin_array_index_for_bin_id,
    decode_bin_array,
    decode_lb_pair,
    dlmm_amount_specific_quote,
    dlmm_reachable_state,
)
from src.providers.raydium_clmm_native import (
    MAX_SQRT_PRICE_X64,
    MAX_TICK,
    MIN_SQRT_PRICE_X64,
    MIN_TICK,
    RAYDIUM_CLMM_PROGRAM_ID,
    ClmmTickArray,
    ClmmTickState,
    _compute_swap_step,
    _delta_amount_0,
    _delta_amount_1,
    clmm_exact_in_quote,
    clmm_tick_array_pda,
    clmm_vault_pda,
    decode_clmm_amm_config,
    decode_clmm_pool_state,
    decode_clmm_tick_array,
    sqrt_price_at_tick,
    tick_array_start_index,
    tick_at_sqrt_price,
)
from src.providers.raydium_cpmm_native import NativeAccount, NativeCaptureError
from tests.meteora_dlmm_fixtures import (
    bin_array_bytes,
    lb_pair_bytes,
    rpc_account as dlmm_account,
)
from tests.native_cpmm_fixtures import address
from tests.raydium_clmm_fixtures import (
    clmm_amm_config_bytes,
    clmm_pool_bytes,
    clmm_tick_array_bytes,
    rpc_account,
)

pytestmark = pytest.mark.unit


def _native(entry):
    return NativeAccount.from_rpc(entry["address"], entry)


def _mutated(entry, *, owner=None, flip_disc=False, truncate=False, patch=None):
    raw = bytearray(base64.b64decode(entry["data"][0]))
    if flip_disc:
        raw[0] ^= 0xFF
    if truncate:
        raw = raw[:-1]
    for offset, value in (patch or {}).items():
        raw[offset] = value
    return rpc_account(entry["address"], owner or entry["owner"], bytes(raw))


def derive_bin_array_pda(pair_id: str, index: int) -> str:
    derived, _ = Pubkey.find_program_address(
        [b"bin_array", bytes(Pubkey.from_string(pair_id)), struct.pack("<q", index)],
        Pubkey.from_string(METEORA_DLMM_PROGRAM_ID),
    )
    return str(derived)


# --- Raydium CLMM scene ------------------------------------------------------


def _clmm_scene(
    *,
    tick_current=100,
    liquidity=10_000_000_000_000,
    trade_fee_rate=0,
    fee_on=0,
    status=0,
    ticks=None,
    bitmap_bits=(513,),
):
    """One-array scene: spacing 1, tick 100 sits in array start 60 (slot 40)."""
    config_entry = rpc_account(
        address(12),
        RAYDIUM_CLMM_PROGRAM_ID,
        clmm_amm_config_bytes(trade_fee_rate=trade_fee_rate),
    )
    config = decode_clmm_amm_config(_native(config_entry))
    pool_bytes, pool_id, mints = clmm_pool_bytes(
        config_address=config_entry["address"],
        tick_current=tick_current,
        liquidity=liquidity,
        fee_on=fee_on,
        status=status,
        bitmap_bits=bitmap_bits,
    )
    pool_entry = rpc_account(pool_id, RAYDIUM_CLMM_PROGRAM_ID, pool_bytes)
    pool = decode_clmm_pool_state(_native(pool_entry))
    start = tick_array_start_index(tick_current, pool.tick_spacing)
    arrays = []
    for array_start, layout in (ticks or {}).items():
        data = clmm_tick_array_bytes(
            pool_id, array_start, tick_spacing=pool.tick_spacing, initialized=layout
        )
        entry = rpc_account(
            clmm_tick_array_pda(pool_id, array_start), RAYDIUM_CLMM_PROGRAM_ID, data
        )
        arrays.append(
            decode_clmm_tick_array(
                _native(entry), expected_pool=pool_id, expected_start=array_start
            )
        )
    return {
        "config_entry": config_entry,
        "config": config,
        "pool_entry": pool_entry,
        "pool": pool,
        "pool_id": pool_id,
        "mints": mints,
        "start": start,
        "arrays": tuple(arrays),
    }


# --- vendored differential vectors (tick_math.rs.txt) -----------------------


def test_clmm_tick_math_matches_vendored_boundaries():
    assert sqrt_price_at_tick(MIN_TICK) == MIN_SQRT_PRICE_X64
    assert sqrt_price_at_tick(MAX_TICK) == MAX_SQRT_PRICE_X64
    assert tick_at_sqrt_price(MIN_SQRT_PRICE_X64) == MIN_TICK
    assert tick_at_sqrt_price(MAX_SQRT_PRICE_X64 - 1) == MAX_TICK - 1


def test_clmm_tick_round_trip_matches_vendored_rounding_vectors():
    sp = sqrt_price_at_tick(-28861)
    assert tick_at_sqrt_price(sp) == -28861
    assert tick_at_sqrt_price(sp + 1) == -28861
    assert tick_at_sqrt_price(sqrt_price_at_tick(-28860) - 1) == -28861
    assert tick_at_sqrt_price(sp - 1) == -28862
    sp = sqrt_price_at_tick(28861)
    assert tick_at_sqrt_price(sp) == 28861
    assert tick_at_sqrt_price(sp + 1) == 28861
    assert tick_at_sqrt_price(sqrt_price_at_tick(28862) - 1) == 28861
    assert tick_at_sqrt_price(sp - 1) == 28860


def test_clmm_tick_sequence_property_over_dense_sample():
    for tick in range(MIN_TICK + 1, MAX_TICK, 997):
        assert sqrt_price_at_tick(tick - 1) < sqrt_price_at_tick(tick)
    for tick in range(MIN_TICK, MAX_TICK, 331):
        value = sqrt_price_at_tick(tick)
        back = tick_at_sqrt_price(value)
        assert sqrt_price_at_tick(back) <= value < sqrt_price_at_tick(back + 1)


# --- pinned swap-step identities --------------------------------------------


def test_clmm_target_identity_and_fee_split_rules():
    import random

    random.seed(20261113)
    hits = overflow = 0
    for _ in range(200):
        t1 = random.randint(-300000, 300000)
        t2 = t1 + random.randint(-3000, 3000)
        if t1 == t2 or not MIN_TICK <= t2 <= MAX_TICK:
            continue
        liquidity = random.randint(1, 1 << 50)
        current = sqrt_price_at_tick(max(t1, t2))
        target = sqrt_price_at_tick(min(t1, t2))
        try:
            d0 = _delta_amount_0(target, current, liquidity, round_up=True)
            d1 = _delta_amount_1(target, current, liquidity, round_up=False)
        except NativeCaptureError as exc:
            assert "MaxTokenOverflow" in str(exc)
            overflow += 1
            continue
        for fee_rate, fee_on_input in ((0, True), (0, False)):
            nxt, ain, aout, fee = _compute_swap_step(
                current,
                target,
                liquidity,
                d0,
                fee_rate,
                zero_for_one=True,
                is_fee_on_input=fee_on_input,
            )
            assert nxt == target and aout == d1
            if fee_on_input:
                assert ain + fee == d0
            else:
                assert ain == d0
        hits += 1
    assert hits > 120 and overflow > 0


def test_clmm_fee_invariant_holds_on_partial_steps():
    import random

    random.seed(99)
    for _ in range(200):
        tick = random.randint(-100000, 100000)
        current = sqrt_price_at_tick(tick)
        target = sqrt_price_at_tick(max(MIN_TICK, tick - random.randint(1, 500)))
        liquidity = random.randint(1, 1 << 50)
        amount = random.randint(1, 1 << 45)
        fee_rate = random.randint(0, 999_999)
        try:
            nxt, ain, aout, fee = _compute_swap_step(
                current,
                target,
                liquidity,
                amount,
                fee_rate,
                zero_for_one=True,
                is_fee_on_input=True,
            )
        except NativeCaptureError as exc:
            assert "MaxTokenOverflow" in str(exc)
            continue
        if nxt != target:
            assert ain + fee == amount and aout > 0
        else:
            assert ain + fee <= amount


# --- CLMM decoder positive/negative matrix ----------------------------------


def test_clmm_pool_decode_binds_pda_vaults_mints_and_status():
    pool = _clmm_scene()["pool"]
    assert pool.token_mint_0 < pool.token_mint_1
    assert pool.token_vault_0 == clmm_vault_pda(pool.address, pool.token_mint_0)
    assert pool.token_vault_1 == clmm_vault_pda(pool.address, pool.token_mint_1)
    assert pool.swap_enabled and pool.mint_decimals_0 == 9
    assert pool.dynamic_fee_raw == bytes(80)
    assert pool.amm_config == address(12)


def test_clmm_pool_decoder_negative_matrix():
    entry = _clmm_scene()["pool_entry"]
    with pytest.raises(NativeCaptureError, match="owner, executable or size"):
        decode_clmm_pool_state(_native(_mutated(entry, owner=address(30))))
    with pytest.raises(NativeCaptureError, match="layout/discriminator"):
        decode_clmm_pool_state(_native(_mutated(entry, flip_disc=True)))
    with pytest.raises(NativeCaptureError, match="layout/discriminator"):
        decode_clmm_pool_state(_native(_mutated(entry, truncate=True)))
    with pytest.raises(NativeCaptureError, match="seed_index"):
        decode_clmm_pool_state(_native(_mutated(entry, patch={391: 1})))


def test_clmm_tick_array_rejects_pool_start_and_pda_mismatch():
    scene = _clmm_scene()
    start = scene["start"]
    foreign = rpc_account(
        clmm_tick_array_pda(address(40), start),
        RAYDIUM_CLMM_PROGRAM_ID,
        clmm_tick_array_bytes(address(40), start, initialized={10: (5, 5)}),
    )
    with pytest.raises(NativeCaptureError, match="binding mismatch"):
        decode_clmm_tick_array(
            _native(foreign), expected_pool=scene["pool_id"], expected_start=start
        )
    good_data = clmm_tick_array_bytes(scene["pool_id"], start, initialized={10: (5, 5)})
    wrong_pda = rpc_account(address(41), RAYDIUM_CLMM_PROGRAM_ID, good_data)
    decoded_wrong = decode_clmm_tick_array(
        _native(wrong_pda), expected_pool=scene["pool_id"], expected_start=start
    )
    with pytest.raises(NativeCaptureError, match="PDA mismatch"):
        clmm_exact_in_quote(
            scene["pool"], scene["config"], (decoded_wrong,), 1_000, zero_for_one=True
        )


def test_clmm_quote_crosses_initialized_ticks_and_accounts_fees():
    scene = _clmm_scene(ticks={60: {30: (1_000_000_000_000, 2_000_000_000_000)}})
    quote = clmm_exact_in_quote(
        scene["pool"], scene["config"], scene["arrays"], 10**10, zero_for_one=True
    )
    assert quote.amount_in + quote.fee_amount == 10**10
    assert quote.amount_out > 0
    assert quote.tick_end <= 90
    assert 90 in quote.crossed_ticks
    # A partial step leaves the current tick unchanged and crosses nothing.
    dust = clmm_exact_in_quote(
        scene["pool"], scene["config"], scene["arrays"], 1_000_000, zero_for_one=True
    )
    assert dust.crossed_ticks == () and dust.tick_end == 100 and dust.amount_out > 0
    priced = _clmm_scene(
        trade_fee_rate=3_000,
        ticks={60: {30: (1_000_000_000_000, 2_000_000_000_000)}},
    )
    quote2 = clmm_exact_in_quote(
        priced["pool"], priced["config"], priced["arrays"], 1_000_000, zero_for_one=True
    )
    assert quote2.amount_in + quote2.fee_amount == 1_000_000
    assert quote2.fee_amount > 0


def test_clmm_quote_amount_sensitivity_across_boundaries():
    scene = _clmm_scene(ticks={60: {30: (1_000_000_000_000, 2_000_000_000_000)}})
    small = clmm_exact_in_quote(
        scene["pool"], scene["config"], scene["arrays"], 1_000, zero_for_one=True
    )
    big = clmm_exact_in_quote(
        scene["pool"],
        scene["config"],
        scene["arrays"],
        10**10,
        zero_for_one=True,
    )
    assert big.amount_out > small.amount_out
    assert len(big.crossed_ticks) >= len(small.crossed_ticks)
    assert big.tick_end <= small.tick_end


def test_clmm_quote_crossing_to_zero_liquidity_fails_closed():
    # The boundary below carries net -current-liquidity, so crossing it leaves
    # zero liquidity while input remains.
    scene = _clmm_scene(
        liquidity=10_000_000_000_000,
        ticks={60: {30: (-10_000_000_000_000, 10_000_000_000_000)}},
    )
    with pytest.raises(NativeCaptureError, match="INSUFFICIENT_ACTIVE_LIQUIDITY"):
        clmm_exact_in_quote(
            scene["pool"],
            scene["config"],
            scene["arrays"],
            1_000_000_000_000_000,
            zero_for_one=True,
        )


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("status", "swap disabled"),
        ("fee-on", "fee_on"),
        ("zero-liquidity", "INSUFFICIENT_ACTIVE_LIQUIDITY"),
        ("no-active-array", "tick array set empty"),
        ("not-in-bitmap", "NOT_INITIALIZED_IN_BITMAP"),
        ("pool-mismatch", "pool binding mismatch"),
        ("duplicate", "duplicate tick array"),
        ("amount-zero", "amount out of u64 range"),
        ("vault", "vault0 PDA"),
        ("pool-pda", "pool PDA"),
        ("config-spacing", "tick spacing mismatch"),
    ],
)
def test_clmm_quote_negative_matrix(fault, reason):
    from dataclasses import replace

    kwargs = {}
    if fault == "status":
        kwargs["status"] = 1 << 4
    if fault == "fee-on":
        kwargs["fee_on"] = 3
    if fault == "zero-liquidity":
        kwargs["liquidity"] = 0
    kwargs.setdefault("ticks", {60: {}})
    scene = _clmm_scene(**kwargs)
    arrays = scene["arrays"]
    pool = scene["pool"]
    config = scene["config"]
    if fault == "no-active-array":
        arrays = tuple(a for a in arrays if a.start_tick_index != scene["start"])
    elif fault == "not-in-bitmap":
        far_start = scene["start"] - 60 * pool.tick_spacing
        arrays = arrays + (
            ClmmTickArray(
                clmm_tick_array_pda(scene["pool_id"], far_start),
                scene["pool_id"],
                far_start,
                (ClmmTickState(far_start, 1, 1, 0, 0),),
                1,
            ),
        )
    elif fault == "pool-mismatch":
        arrays = (
            ClmmTickArray(
                arrays[0].address,
                address(44),
                arrays[0].start_tick_index,
                arrays[0].ticks,
                0,
            ),
        )
    elif fault == "duplicate":
        arrays = arrays + (arrays[0],)
    elif fault == "vault":
        pool = replace(pool, token_vault_0=address(45))
    elif fault == "pool-pda":
        mutated_mint = address(46)
        pool = replace(
            pool,
            token_mint_0=mutated_mint,
            token_vault_0=clmm_vault_pda(pool.address, mutated_mint),
        )
    elif fault == "config-spacing":
        config = replace(config, tick_spacing=2)
    amount = 0 if fault == "amount-zero" else 1_000
    with pytest.raises(NativeCaptureError, match=reason):
        clmm_exact_in_quote(pool, config, arrays, amount, zero_for_one=True)


def test_clmm_extension_range_fails_closed_without_extension_account():
    scene = _clmm_scene(bitmap_bits=(513,))
    far_start = scene["pool"].tick_spacing * 60 * 600  # beyond +/-512 arrays
    with pytest.raises(NativeCaptureError, match="BITMAP_EXTENSION_REQUIRED"):
        clmm_exact_in_quote(
            scene["pool"],
            scene["config"],
            scene["arrays"]
            + (
                ClmmTickArray(
                    clmm_tick_array_pda(scene["pool_id"], far_start),
                    scene["pool_id"],
                    far_start,
                    (ClmmTickState(far_start, 1, 1, 0, 0),),
                    1,
                ),
            ),
            1_000,
            zero_for_one=True,
        )


# --- Meteora DLMM: decoders, walk, and the missing-pin boundary -------------


def _dlmm_scene(*, active_id=5, status=0, token_flags=(0, 0), version=0):
    pair_bytes, pair_id, mints = lb_pair_bytes(
        active_id=active_id, status=status, token_flags=token_flags, version=version
    )
    pair = decode_lb_pair(
        _native(dlmm_account(pair_id, METEORA_DLMM_PROGRAM_ID, pair_bytes))
    )
    return pair_bytes, pair_id, mints, pair


def test_dlmm_lb_pair_decode_state_facts():
    _, _, mints, pair = _dlmm_scene()
    assert pair.active_id == 5 and pair.bin_step == 10
    assert pair.enabled and pair.pair_type_name == "Permissionless"
    assert pair.token_x_mint == mints[0] and pair.token_y_mint == mints[1]
    assert pair.token_x_program == pair.token_y_program
    assert base_fee_rate(pair) == 500 * 10 * 10 * 10**1
    assert pair.protocol_fee_amount_x == 1_000


def test_dlmm_lb_pair_decoder_negative_matrix():
    _, pair_id, _, _ = _dlmm_scene()
    entry = dlmm_account(pair_id, METEORA_DLMM_PROGRAM_ID, lb_pair_bytes()[0])
    with pytest.raises(NativeCaptureError, match="layout/discriminator"):
        decode_lb_pair(_native(_mutated(entry, flip_disc=True)))
    with pytest.raises(NativeCaptureError, match="layout/discriminator"):
        decode_lb_pair(_native(_mutated(entry, truncate=True)))
    with pytest.raises(NativeCaptureError, match="token program flag"):
        decode_lb_pair(_native(_mutated(entry, patch={880: 7})))


def test_dlmm_bin_array_decode_and_bin_mapping():
    _, pair_id, _, _ = _dlmm_scene()
    data = bin_array_bytes(
        pair_id, 0, bins={0: (1_000, 2_000, 1 << 64, 500), 5: (0, 3_000, 1 << 64, 700)}
    )
    entry = dlmm_account(
        derive_bin_array_pda(pair_id, 0), METEORA_DLMM_PROGRAM_ID, data
    )
    array = decode_bin_array(_native(entry), expected_pair=pair_id)
    assert array.index == 0 and array.version == 0
    assert array.bin(0).amount_x == 1_000 and array.bin(5).amount_y == 3_000
    assert array.bin(0).has_liquidity and not array.bin(1).has_liquidity
    assert bin_array_index_for_bin_id(69) == 0
    assert bin_array_index_for_bin_id(70) == 1
    assert bin_array_index_for_bin_id(-1) == -1
    assert bin_array_index_for_bin_id(-70) == -1
    with pytest.raises(NativeCaptureError, match="outside decoded bin array"):
        array.bin(70)
    with pytest.raises(NativeCaptureError, match="version"):
        decode_bin_array(
            _native(
                dlmm_account(
                    derive_bin_array_pda(pair_id, 0),
                    METEORA_DLMM_PROGRAM_ID,
                    bin_array_bytes(pair_id, 0, version=1),
                )
            ),
            expected_pair=pair_id,
        )
    foreign = dlmm_account(
        derive_bin_array_pda(pair_id, 0),
        METEORA_DLMM_PROGRAM_ID,
        bin_array_bytes(address(50), 0),
    )
    with pytest.raises(NativeCaptureError, match="binding mismatch"):
        decode_bin_array(_native(foreign), expected_pair=pair_id)


def test_dlmm_reachable_walk_state_only():
    _, pair_id, _, pair = _dlmm_scene(active_id=3)
    arrays = []
    for index, bins in (
        (
            0,
            {
                0: (100, 200, 1 << 64, 1),
                1: (150, 250, 1 << 64, 1),
                3: (300, 400, 1 << 64, 1),
            },
        ),
        (-1, {69: (500, 600, 1 << 64, 1)}),
    ):
        arrays.append(
            decode_bin_array(
                _native(
                    dlmm_account(
                        derive_bin_array_pda(pair_id, index),
                        METEORA_DLMM_PROGRAM_ID,
                        bin_array_bytes(pair_id, index, bins=bins),
                    )
                ),
                expected_pair=pair_id,
            )
        )
    state = dlmm_reachable_state(pair, tuple(arrays), swap_for_y=True, max_bins=6)
    assert state.amount_specific_quote == "DLMM_AMOUNT_SPECIFIC_QUOTE_MISSING_PIN"
    assert state.evidence_state == "VENUE_STATE_DECODED"
    ids = [b[0] for b in state.reachable_bins]
    # swap_for_y walks the active id downward (pinned advance rule).
    assert ids[0] == 3 and all(b < a for a, b in zip(ids, ids[1:]))
    assert set(ids) <= {3, 2, 1, 0, -1}
    assert len(state.bin_arrays_used) == 2
    with pytest.raises(NativeCaptureError, match="MISSING_PIN"):
        dlmm_amount_specific_quote(state)


def test_dlmm_negative_matrix():
    from dataclasses import replace

    _, pair_id, _, pair = _dlmm_scene()
    disabled = _dlmm_scene(status=1)[3]
    with pytest.raises(NativeCaptureError, match="disabled"):
        dlmm_reachable_state(disabled, (), swap_for_y=True)
    with pytest.raises(NativeCaptureError, match="active bin array missing"):
        dlmm_reachable_state(pair, (), swap_for_y=True)
    good = decode_bin_array(
        _native(
            dlmm_account(
                derive_bin_array_pda(pair_id, 0),
                METEORA_DLMM_PROGRAM_ID,
                bin_array_bytes(pair_id, 0, bins={5: (1, 1, 1 << 64, 1)}),
            )
        ),
        expected_pair=pair_id,
    )
    with pytest.raises(NativeCaptureError, match="missing"):
        dlmm_reachable_state(replace(pair, active_id=200), (good,), swap_for_y=False)
    # Token-2022 flag accepted and mapped to the pinned program id.
    pair2022 = _dlmm_scene(token_flags=(1, 0))[3]
    assert pair2022.token_x_program == "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
