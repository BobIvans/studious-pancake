"""Strict Raydium CLMM (concentrated liquidity) direct-state decoding and exact-in math.

Canonical owner for Raydium CLMM pool state, AMM config, tick arrays, the pool
tick-array bitmap and the amount-specific ExactIn quote. Layouts and math rules
are transcribed from the pinned offline vendor snapshot
``docs/integrations/offline/solana-p0/vendor-reference/raydium/clmm/*``
(raydium-io/raydium-clmm @ 6d7a0f82d2f293c553c69aaf943377367c6c4cc6, Apache-2.0;
git blob hashes pinned in ``VENDOR_SOURCE_MANIFEST.json`` and
``SOURCE_MANIFEST.json``).

Provenance tags used in comments:
- ``[PINNED]``: transcribed from a mirrored upstream file.
- ``[DOCUMENTED]``: arithmetic from the same pinned program family for files
  outside the mirrored set (``liquidity_math.rs`` amount-1 delta,
  ``sqrt_price_math.rs`` next-price form, ``swap.rs`` fee split). Every such
  site is marked and the quote result exposes ``math_provenance`` so consumers
  cannot mistake it for a vendor vector.

Fail-closed policy: unknown layout/discriminator, wrong program owner, pool PDA
mismatch, truncated accounts, paused swap, unknown status bits, Token-2022 or
unknown token programs, nonzero ``dynamic_fee_info`` (layout not mirrored),
tick arrays missing from the provided coherent set, and default-bitmap overflow
for tick_spacing < 15 (pinned pool.rs then requires a TickArrayBitmapExtension
account whose layout is not mirrored) all raise :class:`ClmmCaptureError`.
Unknown is never zero and no quote is returned from incomplete tick data.
No signer, no sender, no network: the only accepted evidence is an offline
coherent capture envelope; any attempt to authorize a live capture is rejected.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
from typing import Any, Mapping

from solders.pubkey import Pubkey

from src.providers.raydium_cpmm_native import NativeAccount, NativeCaptureError
from src.providers.raydium_cpmm_native import content_hash
from src.strategy.exact_cpmm_capacity import MAINNET_GENESIS, SPL_TOKEN_PROGRAM

SCHEMA = "shadow.raydium-clmm-native-capture.v1"
DECODER_REVISION = "p0-3.raydium-clmm-native.v1"
SOURCE_REVISION = "raydium-clmm@6d7a0f82d2f293c553c69aaf943377367c6c4cc6"

# [PINNED] SOURCE_MANIFEST.json -> raydium_clmm_program.program_id_mainnet
RAYDIUM_CLMM_PROGRAM_ID = "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"
PROGRAM = Pubkey.from_string(RAYDIUM_CLMM_PROGRAM_ID)
LOADER = "BPFLoaderUpgradeab1e11111111111111111111111"
CLOCK = "SysvarC1ock11111111111111111111111111111111"
SYSVAR_OWNER = "Sysvar1111111111111111111111111111111111111"

# [PINNED] clmm/config.rs
FEE_RATE_DENOMINATOR = 1_000_000
MAX_TICK_SPACING = 1000
AMM_CONFIG_SEED = b"amm_config"
POOL_SEED = b"pool"
TICK_ARRAY_SEED = b"tick_array"
# [PINNED] clmm/tick_math.rs
MIN_TICK = -443636
MAX_TICK = 443636
MIN_SQRT_PRICE_X64 = 4295048016
MAX_SQRT_PRICE_X64 = 79226673521066979257578248091
Q64 = 1 << 64
U64_MAX = (1 << 64) - 1
U128_MAX = (1 << 128) - 1

# [PINNED] clmm/tick_array.rs TICK_ARRAY_SIZE; clmm/tick_array_bit_map.rs
TICK_ARRAY_SIZE = 60
TICK_ARRAY_BITMAP_SIZE = 512

# [PINNED] clmm/pool.rs PoolState (#[repr(C, packed)], PoolState::LEN = 1544)
POOL_STATE_LEN = 1544
AMM_CONFIG_LEN = 117  # [PINNED] clmm/config.rs AmmConfig::LEN
TICK_ARRAY_STATE_LEN = 10720  # [PINNED] clmm/tick_array.rs TickArrayState::LEN
TICK_STATE_LEN = 176  # [PINNED] clmm/tick_array.rs TickState::LEN
STATUS_DEFINED_MASK = 0b0011_1111  # bits 0..5 defined (PoolStatusBitIndex)
STATUS_SWAP_BIT = 1 << 4  # bit 4 = Swap
FEE_ON_VALUES = (0, 1, 2)  # 0 FromInput, 1 Token0Only, 2 Token1Only

_U1024_MASK = (1 << 1024) - 1

# [PINNED] tick_math.rs magic factors, verbatim. factor[i] is
# 2^64 / 1.0001^(2^(i-1)) for i in [0, 19) and is applied when bit i of |tick|
# is set (the Rust code applies factor 0 as the initial ratio when bit 0 is set).
_TICK_FACTORS = (
    0xFFFCB933BD6FB800,
    0xFFF97272373D4000,
    0xFFF2E50F5F657000,
    0xFFE5CACA7E10F000,
    0xFFCB9843D60F7000,
    0xFF973B41FA98E800,
    0xFF2EA16466C9B000,
    0xFE5DEE046A9A3800,
    0xFCBE86C7900BB000,
    0xF987A7253AC65800,
    0xF3392B0822BB6000,
    0xE7159475A2CAF000,
    0xD097F3BDFD2F2000,
    0xA9F746462D9F8000,
    0x70D869A156F31C00,
    0x31BE135F97ED3200,
    0x9AA508B5B85A500,
    0x5D6AF8DEDC582C,
    0x2216E584F5FA,
)

assert len(_TICK_FACTORS) == 19
assert _TICK_FACTORS[0] == 0xFFFCB933BD6FB800
assert _TICK_FACTORS[1] == 0xFFF97272373D4000
assert _TICK_FACTORS[18] == 0x2216E584F5FA


class ClmmCaptureError(ValueError):
    """Missing, malformed or incoherent CLMM evidence; never a zero quote."""


def _owned_data(account: NativeAccount, owner: str, length: int | None = None) -> bytes:
    """Fail-closed ownership/length check, re-raised as a venue error."""
    try:
        return account.require(owner, length)
    except NativeCaptureError as exc:
        raise ClmmCaptureError(str(exc)) from exc


def _account_from_rpc(address: Any, value: Any) -> NativeAccount:
    try:
        return NativeAccount.from_rpc(address, value)
    except NativeCaptureError as exc:
        raise ClmmCaptureError(str(exc)) from exc


class _MaxTokenOverflow(Exception):
    """[PINNED] swap_math.rs MaxTokenOverflow: target delta exceeds u64."""


# ---------------------------------------------------------------------------
# Integer decoding helpers
# ---------------------------------------------------------------------------


def _u(data: bytes, offset: int, size: int = 8) -> int:
    return int.from_bytes(data[offset : offset + size], "little")


def _i(data: bytes, offset: int, size: int) -> int:
    return int.from_bytes(data[offset : offset + size], "little", signed=True)


def _pk(data: bytes, offset: int) -> str:
    return str(Pubkey.from_bytes(data[offset : offset + 32]))


def _layout(data: bytes, length: int, name: str) -> None:
    if (
        len(data) != length
        or data[:8] != hashlib.sha256(f"account:{name}".encode()).digest()[:8]
    ):
        raise ClmmCaptureError(f"unsupported {name} layout/discriminator")


def _bounded_u64(value: int, label: str) -> int:
    if not 0 <= value <= U64_MAX:
        raise ClmmCaptureError(f"{label} exceeds u64 range")
    return value


# ---------------------------------------------------------------------------
# Pinned tick math (clmm/tick_math.rs)
# ---------------------------------------------------------------------------


def get_sqrt_price_at_tick(tick: int) -> int:
    """1.0001^(tick/2) as a Q64.64 value. [PINNED tick_math.rs]"""
    if not MIN_TICK <= tick <= MAX_TICK:
        raise ClmmCaptureError("tick outside pinned MIN_TICK/MAX_TICK")
    abs_tick = -tick if tick < 0 else tick
    ratio = 1 << 64
    for i in range(19):
        if abs_tick & (1 << i):
            ratio = (ratio * _TICK_FACTORS[i]) >> 64
    if tick > 0:
        ratio = U128_MAX // ratio
    return ratio


def get_tick_at_sqrt_price(sqrt_price_x64: int) -> int:
    """Greatest tick t with get_sqrt_price_at_tick(t) <= sqrt_price_x64. [PINNED]"""
    if not MIN_SQRT_PRICE_X64 <= sqrt_price_x64 < MAX_SQRT_PRICE_X64:
        raise ClmmCaptureError("sqrt price outside pinned MIN/MAX_SQRT_PRICE_X64")
    msb = sqrt_price_x64.bit_length() - 1  # 128 - leading_zeros - 1
    log2p_integer_x32 = (msb - 64) << 32
    bit = 0x8000_0000_0000_0000
    precision = 0
    log2p_fraction_x64 = 0
    r = sqrt_price_x64 >> (msb - 63) if msb >= 64 else sqrt_price_x64 << (63 - msb)
    while bit > 0 and precision < 16:
        r *= r
        is_r_more_than_two = r >> 127
        r >>= 63 + is_r_more_than_two
        log2p_fraction_x64 += bit * is_r_more_than_two
        bit >>= 1
        precision += 1
    log2p_fraction_x32 = log2p_fraction_x64 >> 32
    log2p_x32 = log2p_integer_x32 + log2p_fraction_x32
    log_sqrt_10001_x64 = log2p_x32 * 59543866431248
    tick_low = (log_sqrt_10001_x64 - 184467440737095516) >> 64
    tick_high = (log_sqrt_10001_x64 + 15793534762490258745) >> 64
    if tick_low == tick_high:
        return int(tick_low)
    if get_sqrt_price_at_tick(int(tick_high)) <= sqrt_price_x64:
        return int(tick_high)
    return int(tick_low)


# ---------------------------------------------------------------------------
# Swap math (clmm/swap_math.rs)
# ---------------------------------------------------------------------------


def _div_ceil(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def get_delta_amount_0_unsigned(
    sqrt_ratio_a_x64: int, sqrt_ratio_b_x64: int, liquidity: int, round_up: bool
) -> int:
    """Token 0 delta between two sqrt prices. [PINNED swap_math.rs pre_series]"""
    if sqrt_ratio_a_x64 > sqrt_ratio_b_x64:
        sqrt_ratio_a_x64, sqrt_ratio_b_x64 = sqrt_ratio_b_x64, sqrt_ratio_a_x64
    if sqrt_ratio_a_x64 <= 0:
        raise ClmmCaptureError("zero sqrt price")
    numerator_1 = liquidity << 64
    numerator_2 = sqrt_ratio_b_x64 - sqrt_ratio_a_x64
    if round_up:
        first = _div_ceil(numerator_1 * numerator_2, sqrt_ratio_b_x64)
        result = _div_ceil(first, sqrt_ratio_a_x64)
    else:
        result = (numerator_1 * numerator_2 // sqrt_ratio_b_x64) // sqrt_ratio_a_x64
    if result > U64_MAX:
        raise _MaxTokenOverflow()
    return result


def get_delta_amount_1_unsigned(
    sqrt_ratio_a_x64: int, sqrt_ratio_b_x64: int, liquidity: int, round_up: bool
) -> int:
    """Token 1 delta between two sqrt prices. [DOCUMENTED liquidity_math.rs]"""
    if sqrt_ratio_a_x64 > sqrt_ratio_b_x64:
        sqrt_ratio_a_x64, sqrt_ratio_b_x64 = sqrt_ratio_b_x64, sqrt_ratio_a_x64
    if sqrt_ratio_a_x64 <= 0:
        raise ClmmCaptureError("zero sqrt price")
    delta = sqrt_ratio_b_x64 - sqrt_ratio_a_x64
    product = liquidity * delta
    if product > U128_MAX:
        raise ClmmCaptureError("liquidity * delta exceeds u128 (CalculateOverflow)")
    result = _div_ceil(product, Q64) if round_up else product // Q64
    if result > U64_MAX:
        raise _MaxTokenOverflow()
    return result


def get_next_sqrt_price_from_input(
    sqrt_price_x64: int, liquidity: int, amount_in: int, zero_for_one: bool
) -> int:
    """Next sqrt price after spending ``amount_in``. [DOCUMENTED sqrt_price_math.rs]

    zero_for_one (token 0 in, price down): from x = L*(1/sqrt_a - 1/sqrt_b),
    sqrt_b_x64 = (L*2^64*sqrt_a_x64) / (L*2^64 + x*sqrt_a_x64), floored.
    one_for_zero (token 1 in, price up): sqrt_b_x64 = sqrt_a_x64 + ceil(x*2^64/L).
    Rounding matches the Uniswap-style naming retained upstream
    (amount_0 -> rounding down, amount_1 -> rounding up).
    """
    if liquidity <= 0:
        raise ClmmCaptureError("invalid liquidity for next sqrt price")
    if amount_in == 0:
        raise ClmmCaptureError("not enough input for next sqrt price")
    if zero_for_one:
        numerator = (liquidity << 64) * sqrt_price_x64
        denominator = (liquidity << 64) + amount_in * sqrt_price_x64
        return numerator // denominator
    return sqrt_price_x64 + _div_ceil(amount_in << 64, liquidity)


@dataclass(frozen=True, slots=True)
class SwapStep:
    """One compute_swap step. [PINNED swap_math.rs SwapComputationResult]"""

    sqrt_price_next_x64: int
    amount_in: int
    amount_out: int
    fee_amount: int


def compute_swap_step(
    sqrt_price_current_x64: int,
    sqrt_price_target_x64: int,
    liquidity: int,
    amount_remaining: int,
    fee_rate: int,
    *,
    zero_for_one: bool,
    is_fee_on_input: bool,
) -> SwapStep:
    """[PINNED swap_math.rs compute_swap, exact-input path] (is_base_input=True).

    The exact-output branches of the pinned function are out of scope for this
    exact-in owner and are intentionally not transcribed.
    """
    if fee_rate >= FEE_RATE_DENOMINATOR:
        raise ClmmCaptureError("fee rate at or above denominator")
    if is_fee_on_input:
        amount_for_price_calc = (
            amount_remaining * (FEE_RATE_DENOMINATOR - fee_rate)
        ) // FEE_RATE_DENOMINATOR
    else:
        amount_for_price_calc = amount_remaining

    try:
        if zero_for_one:
            amount_in_at_target = get_delta_amount_0_unsigned(
                sqrt_price_target_x64, sqrt_price_current_x64, liquidity, True
            )
            amount_out_at_target = get_delta_amount_1_unsigned(
                sqrt_price_target_x64, sqrt_price_current_x64, liquidity, False
            )
        else:
            amount_in_at_target = get_delta_amount_1_unsigned(
                sqrt_price_current_x64, sqrt_price_target_x64, liquidity, True
            )
            amount_out_at_target = get_delta_amount_0_unsigned(
                sqrt_price_current_x64, sqrt_price_target_x64, liquidity, False
            )
        target_reached = amount_for_price_calc >= amount_in_at_target
    except _MaxTokenOverflow:
        # [PINNED] MaxTokenOverflow at the target means the target is unreachable
        # at u64 precision and the step solves for the reachable price instead.
        target_reached = False

    if target_reached:
        sqrt_price_next_x64 = sqrt_price_target_x64
        amount_in, amount_out = amount_in_at_target, amount_out_at_target
    else:
        sqrt_price_next_x64 = get_next_sqrt_price_from_input(
            sqrt_price_current_x64,
            liquidity,
            amount_for_price_calc,
            zero_for_one,
        )
        if zero_for_one:
            amount_in = get_delta_amount_0_unsigned(
                sqrt_price_next_x64, sqrt_price_current_x64, liquidity, True
            )
            amount_out = get_delta_amount_1_unsigned(
                sqrt_price_next_x64, sqrt_price_current_x64, liquidity, False
            )
        else:
            amount_in = get_delta_amount_1_unsigned(
                sqrt_price_current_x64, sqrt_price_next_x64, liquidity, True
            )
            amount_out = get_delta_amount_0_unsigned(
                sqrt_price_current_x64, sqrt_price_next_x64, liquidity, False
            )

    if is_fee_on_input:
        if sqrt_price_next_x64 != sqrt_price_target_x64:
            fee_amount = amount_remaining - amount_in
        else:
            fee_amount = _div_ceil(
                amount_in * fee_rate, FEE_RATE_DENOMINATOR - fee_rate
            )
    else:
        # Fee from output: the pinned dust fix charges the full input on a
        # partial step so the swap loop cannot stall.
        fee_amount = _div_ceil(amount_out * fee_rate, FEE_RATE_DENOMINATOR)
        amount_out -= fee_amount
        if sqrt_price_next_x64 != sqrt_price_target_x64:
            amount_in = amount_remaining

    if zero_for_one and sqrt_price_next_x64 < sqrt_price_target_x64:
        raise ClmmCaptureError("sqrt price moved past the target boundary")
    if not zero_for_one and sqrt_price_next_x64 > sqrt_price_target_x64:
        raise ClmmCaptureError("sqrt price moved past the target boundary")
    return SwapStep(sqrt_price_next_x64, amount_in, amount_out, fee_amount)


# ---------------------------------------------------------------------------
# Pinned tick-array bitmap helpers (clmm/tick_array_bit_map.rs, clmm/pool.rs)
# ---------------------------------------------------------------------------


def _trunc_div(a: int, b: int) -> int:
    """Rust integer division: truncation toward zero (Python floors)."""
    return a // b if a >= 0 else -((-a) // b)


def _rust_rem(a: int, b: int) -> int:
    """Rust remainder: sign follows the dividend."""
    return a - _trunc_div(a, b) * b


def max_tick_in_tickarray_bitmap(tick_spacing: int) -> int:
    """[PINNED tick_array_bit_map.rs]"""
    return tick_spacing * TICK_ARRAY_SIZE * TICK_ARRAY_BITMAP_SIZE


def array_start_index(tick_index: int, tick_spacing: int) -> int:
    """[PINNED TickArrayState::get_array_start_index] (Rust truncating division)"""
    ticks_in_array = TICK_ARRAY_SIZE * tick_spacing
    start = _trunc_div(tick_index, ticks_in_array)
    if tick_index < 0 and _rust_rem(tick_index, ticks_in_array) != 0:
        start -= 1
    return start * ticks_in_array


def check_is_valid_start_index(tick_index: int, tick_spacing: int) -> bool:
    """[PINNED TickArrayState::check_is_valid_start_index]"""
    if tick_index < MIN_TICK or tick_index > MAX_TICK:
        if tick_index > MAX_TICK:
            return False
        return tick_index == array_start_index(MIN_TICK, tick_spacing)
    return tick_index % (TICK_ARRAY_SIZE * tick_spacing) == 0


def is_overflow_default_bitmap(tick_index: int, tick_spacing: int) -> bool:
    """[PINNED pool.rs is_overflow_default_tickarray_bitmap + range logic]"""
    max_boundary = max_tick_in_tickarray_bitmap(tick_spacing)
    min_boundary = -max_boundary
    if max_boundary > MAX_TICK:
        max_boundary = array_start_index(MAX_TICK, tick_spacing)
        max_boundary += TICK_ARRAY_SIZE * tick_spacing
    if min_boundary < MIN_TICK:
        min_boundary = array_start_index(MIN_TICK, tick_spacing)
    array_start = array_start_index(tick_index, tick_spacing)
    return array_start >= max_boundary or array_start < min_boundary


def check_current_tick_array_is_initialized(
    bit_map: int, tick_current: int, tick_spacing: int
) -> tuple[bool, int]:
    """[PINNED tick_array_bit_map.rs] (Rust truncating division/remainder)"""
    if tick_current < MIN_TICK or tick_current > MAX_TICK:
        raise ClmmCaptureError("invalid tick index for bitmap check")
    multiplier = tick_spacing * TICK_ARRAY_SIZE
    compressed = _trunc_div(tick_current, multiplier) + TICK_ARRAY_BITMAP_SIZE
    if tick_current < 0 and _rust_rem(tick_current, multiplier) != 0:
        compressed -= 1
    bit_pos = abs(compressed)
    initialized = (bit_map >> bit_pos) & 1 == 1
    return initialized, (compressed - TICK_ARRAY_BITMAP_SIZE) * multiplier


def next_initialized_tick_array_start_index(
    bit_map: int,
    last_tick_array_start_index: int,
    tick_spacing: int,
    zero_for_one: bool,
) -> tuple[bool, int]:
    """[PINNED tick_array_bit_map.rs] Default U1024 pool bitmap search."""
    if not check_is_valid_start_index(last_tick_array_start_index, tick_spacing):
        raise ClmmCaptureError("invalid tick array boundary")
    tick_boundary = max_tick_in_tickarray_bitmap(tick_spacing)
    tick_count = TICK_ARRAY_SIZE * tick_spacing
    next_start = (
        last_tick_array_start_index - tick_count
        if zero_for_one
        else last_tick_array_start_index + tick_count
    )
    if next_start < -tick_boundary or next_start >= tick_boundary:
        return False, last_tick_array_start_index
    multiplier = tick_spacing * TICK_ARRAY_SIZE
    compressed = _trunc_div(next_start, multiplier) + TICK_ARRAY_BITMAP_SIZE
    if next_start < 0 and _rust_rem(next_start, multiplier) != 0:
        compressed -= 1
    bit_pos = abs(compressed)
    if zero_for_one:
        offset_bitmap = (bit_map << (1024 - bit_pos - 1)) & _U1024_MASK
        if offset_bitmap == 0:
            return False, -tick_boundary
        next_bit = 1024 - offset_bitmap.bit_length()  # most_significant_bit
        return True, (bit_pos - next_bit - TICK_ARRAY_BITMAP_SIZE) * multiplier
    offset_bitmap = bit_map >> bit_pos
    if offset_bitmap == 0:
        return False, tick_boundary - tick_count
    next_bit = (
        offset_bitmap & -offset_bitmap
    ).bit_length() - 1  # least_significant_bit
    return True, (bit_pos + next_bit - TICK_ARRAY_BITMAP_SIZE) * multiplier


# ---------------------------------------------------------------------------
# Account decoding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClmmPoolState:
    address: str
    amm_config: str
    owner: str
    token_mint_0: str
    token_mint_1: str
    token_vault_0: str
    token_vault_1: str
    mint_decimals_0: int
    mint_decimals_1: int
    tick_spacing: int
    liquidity: int
    sqrt_price_x64: int
    tick_current: int
    fee_growth_global_0_x64: int
    fee_growth_global_1_x64: int
    protocol_fees_token_0: int
    protocol_fees_token_1: int
    status: int
    fee_on: int
    tick_array_bitmap: int
    fund_fees_token_0: int
    fund_fees_token_1: int
    open_time: int
    recent_epoch: int
    dynamic_fee_info_zero: bool
    data_sha256: str


def decode_pool(account: NativeAccount) -> ClmmPoolState:
    data = _owned_data(account, RAYDIUM_CLMM_PROGRAM_ID)
    _layout(data, POOL_STATE_LEN, "PoolState")
    bump = data[8]
    amm_config = _pk(data, 9)
    token_mint_0 = _pk(data, 73)
    token_mint_1 = _pk(data, 105)
    seed_index = data[391:393]
    # [PINNED pool.rs PoolState::seeds] seeds = [pool, amm_config, mint0, mint1,
    # ([] if seed_index == [0, 0] else seed_index), bump] via create_program_address.
    seed_bytes = b"" if seed_index == b"\x00\x00" else seed_index
    try:
        expected_pool = Pubkey.create_program_address(
            [
                POOL_SEED,
                bytes(Pubkey.from_string(amm_config)),
                bytes(Pubkey.from_string(token_mint_0)),
                bytes(Pubkey.from_string(token_mint_1)),
                seed_bytes,
                bytes([bump]),
            ],
            PROGRAM,
        )
    except ValueError as exc:
        raise ClmmCaptureError("pool PDA derivation failed") from exc
    if str(expected_pool) != account.address:
        raise ClmmCaptureError("pool address is not the pinned PDA")
    tick_spacing = _u(data, 235, 2)
    if not 1 <= tick_spacing <= MAX_TICK_SPACING:
        raise ClmmCaptureError("tick spacing outside pinned bounds")
    sqrt_price_x64 = _u(data, 253, 16)
    if not MIN_SQRT_PRICE_X64 <= sqrt_price_x64 < MAX_SQRT_PRICE_X64:
        raise ClmmCaptureError("sqrt price outside pinned bounds")
    tick_current = _i(data, 269, 4)
    if not MIN_TICK <= tick_current <= MAX_TICK:
        raise ClmmCaptureError("tick_current outside pinned bounds")
    status = data[389]
    fee_on = data[390]
    if status & ~STATUS_DEFINED_MASK:
        raise ClmmCaptureError("unknown pool status bits")
    if fee_on not in FEE_ON_VALUES:
        raise ClmmCaptureError("unsupported fee_on value")
    if status & STATUS_SWAP_BIT:
        raise ClmmCaptureError("pool swap is disabled by status bit")
    if any(data[1096:1176]):
        raise ClmmCaptureError(
            "dynamic fee state present but DynamicFeeInfo layout is not mirrored; "
            "BLOCKED(DYNAMIC_FEE_LAYOUT_NOT_MIRRORED)"
        )
    return ClmmPoolState(
        account.address,
        amm_config,
        _pk(data, 41),
        token_mint_0,
        token_mint_1,
        _pk(data, 137),
        _pk(data, 169),
        data[233],
        data[234],
        tick_spacing,
        _u(data, 237, 16),
        sqrt_price_x64,
        tick_current,
        _u(data, 277, 16),
        _u(data, 293, 16),
        _u(data, 309),
        _u(data, 317),
        status,
        fee_on,
        _u(data, 904, 128),
        _u(data, 1064),
        _u(data, 1072),
        _u(data, 1080),
        _u(data, 1088),
        all(b == 0 for b in data[1096:1176]),
        hashlib.sha256(data).hexdigest(),
    )


@dataclass(frozen=True, slots=True)
class ClmmAmmConfig:
    address: str
    bump: int
    index: int
    owner: str
    protocol_fee_rate: int
    trade_fee_rate: int
    tick_spacing: int
    fund_fee_rate: int
    data_sha256: str


def decode_amm_config(account: NativeAccount, pool: ClmmPoolState) -> ClmmAmmConfig:
    if account.address != pool.amm_config:
        raise ClmmCaptureError("config account does not match pool pointer")
    data = _owned_data(account, RAYDIUM_CLMM_PROGRAM_ID)
    _layout(data, AMM_CONFIG_LEN, "AmmConfig")
    config = ClmmAmmConfig(
        account.address,
        data[8],
        _u(data, 9, 2),
        _pk(data, 11),
        _u(data, 43, 4),
        _u(data, 47, 4),
        _u(data, 51, 2),
        _u(data, 53, 4),
        hashlib.sha256(data).hexdigest(),
    )
    if config.tick_spacing != pool.tick_spacing:
        raise ClmmCaptureError("config/pool tick spacing mismatch")
    if config.trade_fee_rate >= FEE_RATE_DENOMINATOR:
        raise ClmmCaptureError("trade fee at or above denominator")
    if config.protocol_fee_rate >= FEE_RATE_DENOMINATOR:
        raise ClmmCaptureError("protocol fee at or above denominator")
    if config.fund_fee_rate >= FEE_RATE_DENOMINATOR:
        raise ClmmCaptureError("fund fee at or above denominator")
    return config


@dataclass(frozen=True, slots=True)
class ClmmTickArray:
    address: str
    pool_id: str
    start_tick_index: int
    initialized_tick_count: int
    ticks: tuple[ClmmTickState, ...]
    initialized_flags: tuple[bool, ...]
    data_sha256: str


@dataclass(frozen=True, slots=True)
class ClmmTickState:
    tick: int
    liquidity_net: int
    liquidity_gross: int


def decode_tick_array(account: NativeAccount, pool: ClmmPoolState) -> ClmmTickArray:
    data = _owned_data(account, RAYDIUM_CLMM_PROGRAM_ID)
    _layout(data, TICK_ARRAY_STATE_LEN, "TickArrayState")
    start_index = _i(data, 40, 4)
    pool_id = _pk(data, 8)
    if pool_id != pool.address:
        raise ClmmCaptureError("tick array bound to a different pool")
    # [PINNED tick_array.rs TickArrayState::key] PDA of
    # [tick_array, pool_id, start_tick_index.to_be_bytes()]
    expected_pda, _ = Pubkey.find_program_address(
        [
            TICK_ARRAY_SEED,
            bytes(Pubkey.from_string(pool.address)),
            (start_index & 0xFFFFFFFF).to_bytes(4, "big"),
        ],
        PROGRAM,
    )
    if str(expected_pda) != account.address:
        raise ClmmCaptureError("tick array PDA mismatch")
    if not check_is_valid_start_index(start_index, pool.tick_spacing):
        raise ClmmCaptureError("invalid tick array start index")
    ticks: list[ClmmTickState] = []
    flags: list[bool] = []
    for i in range(TICK_ARRAY_SIZE):
        base = 44 + i * TICK_STATE_LEN
        tick = ClmmTickState(
            _i(data, base, 4),
            _i(data, base + 4, 16),
            _u(data, base + 20),
        )
        # [PINNED tick_array.rs TickState::is_initialized]
        initialized = (
            tick.liquidity_gross > 0
            or _u(data, base + 124) > 0
            or _u(data, base + 132) > 0
        )
        ticks.append(tick)
        flags.append(initialized)
    if data[10604] != sum(flags):
        raise ClmmCaptureError("initialized tick count mismatch")
    return ClmmTickArray(
        account.address,
        pool_id,
        start_index,
        int(data[10604]),
        tuple(ticks),
        tuple(flags),
        hashlib.sha256(data).hexdigest(),
    )


# ---------------------------------------------------------------------------
# Coherent capture envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecodedClmmCapture:
    pool: ClmmPoolState
    config: ClmmAmmConfig
    tick_arrays: tuple[ClmmTickArray, ...]
    mints: tuple[str, str]
    mint_decimals: tuple[int, int]
    vaults: tuple[str, str]
    vault_amounts: tuple[int, int]
    slot: int
    block_time: int
    clock_epoch: int
    binary_sha256: str
    deployment_slot: int
    capture_hash: str
    evidence_kind: str


def _require_bounded_list(payload: Mapping[str, Any], name: str) -> list[Any]:
    raw = payload.get(name)
    if not isinstance(raw, list) or not 1 <= len(raw) <= 200:
        raise ClmmCaptureError(f"bounded {name} list required")
    return raw


def decode_clmm_capture(payload: Mapping[str, Any]) -> DecodedClmmCapture:
    if (
        payload.get("schema") != SCHEMA
        or payload.get("decoder_revision") != DECODER_REVISION
    ):
        raise ClmmCaptureError("unsupported capture schema/decoder")
    if payload.get("source_revision") != SOURCE_REVISION:
        raise ClmmCaptureError("unsupported source revision")
    if (
        payload.get("genesis_hash") != MAINNET_GENESIS
        or payload.get("commitment") != "finalized"
    ):
        raise ClmmCaptureError("wrong genesis or non-finalized capture")
    if payload.get("evidence_kind") not in {"captured-rpc", "synthetic-fixture"}:
        raise ClmmCaptureError("explicit evidence kind required")
    if payload.get("live_capture_authorized"):
        raise ClmmCaptureError("BLOCKED(LIVE_CAPTURE_NOT_AUTHORIZED)")
    slot = payload.get("slot")
    if type(slot) is not int or not 1 <= slot <= 2**63 - 1:
        raise ClmmCaptureError("invalid context slot")
    observed = payload.get("observed_at_ns")
    available = payload.get("available_at_ns")
    if type(observed) is not int or type(available) is not int or available < observed:
        raise ClmmCaptureError("invalid capture timing")
    block = payload.get("block")
    if not isinstance(block, dict):
        raise ClmmCaptureError("rooted block required")
    parent_slot = block.get("parentSlot")
    if type(parent_slot) is not int or parent_slot >= slot:
        raise ClmmCaptureError("parent slot must precede context slot")
    block_hash = block.get("blockhash")
    parent_hash = block.get("previousBlockhash")
    block_time = block.get("blockTime")

    def canonical_key(value: Any) -> str:
        if not isinstance(value, str):
            raise ClmmCaptureError("public key fields must be text")
        try:
            parsed = Pubkey.from_string(value)
        except ValueError as exc:
            raise ClmmCaptureError("invalid public key") from exc
        if str(parsed) != value:
            raise ClmmCaptureError("noncanonical public key")
        return value

    canonical_key(block_hash)
    canonical_key(parent_hash)
    if block_hash == parent_hash:
        raise ClmmCaptureError("block hash equals parent hash")
    if type(block_time) is not int or block_time <= 0 or block_time * 10**9 > available:
        raise ClmmCaptureError("invalid rooted block clock")

    raw = _require_bounded_list(payload, "accounts")
    pool_ids = payload.get("pool_ids")
    if (
        not isinstance(pool_ids, list)
        or len(pool_ids) != 1
        or not isinstance(pool_ids[0], str)
    ):
        raise ClmmCaptureError("require exactly one CLMM pool address")
    pool_id = canonical_key(pool_ids[0])
    metadata = payload.get("account_response_metadata")
    if not isinstance(metadata, dict) or metadata.get("jsonrpc") != "2.0":
        raise ClmmCaptureError("raw account response envelope required")
    response = copy.deepcopy(metadata)
    result = response.get("result")
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("context"), dict)
        or result["context"].get("slot") != slot
        or "value" in result
    ):
        raise ClmmCaptureError("raw account response context mismatch")
    result["value"] = [
        entry.get("value") if isinstance(entry, dict) else None for entry in raw
    ]
    if content_hash(response) != payload.get("account_response_hash"):
        raise ClmmCaptureError("raw account response hash mismatch")

    accounts: dict[str, NativeAccount] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise ClmmCaptureError("invalid raw account entry")
        account = _account_from_rpc(entry.get("address"), entry.get("value"))
        if account.address in accounts:
            raise ClmmCaptureError("duplicate account address")
        accounts[account.address] = account

    def require(address: str) -> NativeAccount:
        try:
            return accounts[address]
        except KeyError as exc:
            raise ClmmCaptureError("incomplete native account set") from exc

    program_account = require(RAYDIUM_CLMM_PROGRAM_ID)
    if program_account.owner != LOADER or not program_account.executable:
        raise ClmmCaptureError("wrong CLMM deployment owner")
    if len(program_account.data) != 36 or _u(program_account.data, 0, 4) != 2:
        raise ClmmCaptureError("unsupported upgradeable program layout")
    program_data_address = _pk(program_account.data, 4)
    programdata = _owned_data(require(program_data_address), LOADER)
    if (
        len(programdata) <= 45
        or _u(programdata, 0, 4) != 3
        or programdata[12] not in (0, 1)
    ):
        raise ClmmCaptureError("unsupported programdata layout")
    deployment_slot = _u(programdata, 4)
    if deployment_slot > slot:
        raise ClmmCaptureError("deployment newer than bank")
    binary_sha256 = hashlib.sha256(programdata[45:]).hexdigest()

    clock = _owned_data(require(CLOCK), SYSVAR_OWNER, 40)
    if _u(clock, 0) != slot:
        raise ClmmCaptureError("clock slot mismatch")
    clock_timestamp = int.from_bytes(clock[32:40], "little", signed=True)
    clock_epoch = _u(clock, 16)
    if abs(clock_timestamp - block_time) > 2:
        raise ClmmCaptureError("clock/block time incoherent")

    pool = decode_pool(require(pool_id))
    config = decode_amm_config(require(pool.amm_config), pool)
    mints: list[str] = []
    decimals: list[int] = []
    for i, mint_address in enumerate((pool.token_mint_0, pool.token_mint_1)):
        mint_data = _owned_data(require(mint_address), SPL_TOKEN_PROGRAM, 82)
        if mint_data[45] != 1:
            raise ClmmCaptureError("uninitialized mint")
        expected_decimals = pool.mint_decimals_0 if i == 0 else pool.mint_decimals_1
        if mint_data[44] != expected_decimals:
            raise ClmmCaptureError("mint decimals mismatch pool state")
        mints.append(mint_address)
        decimals.append(mint_data[44])
    if bytes(Pubkey.from_string(mints[0])) >= bytes(Pubkey.from_string(mints[1])):
        raise ClmmCaptureError("pool mint order is noncanonical")
    vault_amounts: list[int] = []
    for i, vault_address in enumerate((pool.token_vault_0, pool.token_vault_1)):
        vault = _owned_data(require(vault_address), SPL_TOKEN_PROGRAM, 165)
        expected_mint = pool.token_mint_0 if i == 0 else pool.token_mint_1
        if _pk(vault, 0) != expected_mint:
            raise ClmmCaptureError("vault mint binding mismatch")
        if vault[108] != 1 or _u(vault, 72, 4) != 0:
            raise ClmmCaptureError("vault state/delegate mismatch")
        vault_amounts.append(_bounded_u64(_u(vault, 64), "vault amount"))

    expected_accounts = {
        RAYDIUM_CLMM_PROGRAM_ID,
        program_data_address,
        CLOCK,
        pool.address,
        pool.amm_config,
        pool.token_mint_0,
        pool.token_mint_1,
        pool.token_vault_0,
        pool.token_vault_1,
    }
    tick_arrays: list[ClmmTickArray] = []
    tick_array_disc = hashlib.sha256(b"account:TickArrayState").digest()[:8]
    for address, account in accounts.items():
        if address in expected_accounts:
            continue
        if account.data[:8] != tick_array_disc:
            raise ClmmCaptureError("unexpected accounts outside coherent native set")
        tick_arrays.append(decode_tick_array(account, pool))
    if not tick_arrays:
        raise ClmmCaptureError("at least one dependent tick array required")
    expected_accounts.update(tick_array.address for tick_array in tick_arrays)
    if set(accounts) != expected_accounts:
        raise ClmmCaptureError("unexpected accounts outside coherent native set")

    return DecodedClmmCapture(
        pool,
        config,
        tuple(sorted(tick_arrays, key=lambda a: a.start_tick_index)),
        (mints[0], mints[1]),
        (decimals[0], decimals[1]),
        (pool.token_vault_0, pool.token_vault_1),
        (vault_amounts[0], vault_amounts[1]),
        slot,
        block_time,
        clock_epoch,
        binary_sha256,
        deployment_slot,
        content_hash(dict(payload)),
        str(payload["evidence_kind"]),
    )


# ---------------------------------------------------------------------------
# Exact-in tick walk
# ---------------------------------------------------------------------------

MAX_TICK_CROSSINGS = 5000  # bounded computation guard (documented, not upstream)

MATH_PROVENANCE = (
    "PINNED:vendor-reference/raydium/clmm/{pool,tick_array,tick_array_bit_map,"
    "swap_math,tick_math,config}@6d7a0f82d2f293c553c69aaf943377367c6c4cc6",
    "DOCUMENTED:liquidity_math.rs amount_1 delta + sqrt_price_math.rs next-price "
    "form + swap.rs fee split (same pinned program family, files not mirrored)",
)


def is_fee_on_input(zero_for_one: bool, fee_on: int) -> bool:
    """[DOCUMENTED swap.rs CollectFeeOn mapping; field comment pinned in pool.rs]"""
    if fee_on == 0:
        return True
    if fee_on == 1:  # Token0Only: fee collected in token 0
        return zero_for_one
    return not zero_for_one  # Token1Only: fee collected in token 1


@dataclass(frozen=True, slots=True)
class ClmmExactInQuote:
    amount_in: int
    input_left: int
    amount_out: int
    trade_fee: int
    protocol_fee: int
    fund_fee: int
    lp_fee: int
    zero_for_one: bool
    next_sqrt_price_x64: int
    next_liquidity: int
    next_tick_current: int
    tick_crossings: int
    tick_arrays_used: tuple[str, ...]
    fee_on_input: bool
    math_provenance: tuple[str, ...]


def _fee_split(fee: int, config: ClmmAmmConfig) -> tuple[int, int, int]:
    """[DOCUMENTED swap.rs split_fee: floor splits, lp = fee - protocol - fund]"""
    protocol = (fee * config.protocol_fee_rate) // FEE_RATE_DENOMINATOR
    fund = (fee * config.fund_fee_rate) // FEE_RATE_DENOMINATOR
    lp = fee - protocol - fund
    if lp < 0:
        raise ClmmCaptureError("fee split underflow")
    return protocol, fund, lp


def _cross_liquidity(liquidity: int, liquidity_net: int, zero_for_one: bool) -> int:
    """Cross a tick: right-to-left (zero_for_one) subtracts net. [PINNED TickState.cross]"""
    liquidity = liquidity - liquidity_net if zero_for_one else liquidity + liquidity_net
    if not 0 <= liquidity <= U128_MAX:
        raise ClmmCaptureError("liquidity out of u128 after tick cross")
    return liquidity


def clmm_exact_in_quote(
    capture: DecodedClmmCapture, amount_in: int, *, zero_for_one: bool
) -> ClmmExactInQuote:
    """Exact-in quote across initialized ticks from coherent captured state."""
    pool = capture.pool
    config = capture.config
    if type(amount_in) is not int or not 1 <= amount_in <= U64_MAX:
        raise ClmmCaptureError("amount_in must be a positive u64")
    if pool.liquidity == 0:
        raise ClmmCaptureError("BLOCKED(INSUFFICIENT_ACTIVE_LIQUIDITY)")
    arrays_by_start = {a.start_tick_index: a for a in capture.tick_arrays}
    tick_spacing = pool.tick_spacing
    bitmap = pool.tick_array_bitmap
    sqrt_current = pool.sqrt_price_x64
    liquidity = pool.liquidity
    tick_current = pool.tick_current
    # Coherence: price must sit inside [sqrt(tick_current), sqrt(tick_current+1)];
    # the upper edge is inclusive for a swap that ended exactly on a boundary.
    lower_bound = get_sqrt_price_at_tick(tick_current)
    upper_bound = (
        MAX_SQRT_PRICE_X64
        if tick_current + 1 > MAX_TICK
        else get_sqrt_price_at_tick(tick_current + 1)
    )
    if not lower_bound <= sqrt_current <= upper_bound:
        raise ClmmCaptureError("sqrt price/tick_current incoherent")

    fee_rate = config.trade_fee_rate
    fee_on_input = is_fee_on_input(zero_for_one, pool.fee_on)
    remaining = amount_in
    total_out = 0
    total_fee = 0
    crossings = 0
    arrays_used: list[str] = []
    array_start = array_start_index(tick_current, tick_spacing)
    steps = 0

    while remaining > 0:
        steps += 1
        if steps > MAX_TICK_CROSSINGS:
            raise ClmmCaptureError("bounded tick-walk computation limit exceeded")
        tick_array = arrays_by_start.get(array_start)
        if tick_array is None:
            raise ClmmCaptureError(
                f"BLOCKED(MISSING_TICK_ARRAY) start_index={array_start}"
            )
        if tick_array.address not in arrays_used:
            arrays_used.append(tick_array.address)
        # [PINNED TickArrayState::next_initialized_tick] zfo searches ticks
        # <= tick_current (descending); one_for_zero searches ticks > tick_current.
        offset_in_array = (tick_current - array_start) // tick_spacing
        target_tick = None
        if zero_for_one:
            for i in range(offset_in_array, -1, -1):
                if tick_array.initialized_flags[i]:
                    target_tick = tick_array.ticks[i].tick
                    break
        else:
            for i in range(offset_in_array + 1, TICK_ARRAY_SIZE):
                if tick_array.initialized_flags[i]:
                    target_tick = tick_array.ticks[i].tick
                    break
        if target_tick is None:
            found, next_start = next_initialized_tick_array_start_index(
                bitmap, array_start, tick_spacing, zero_for_one
            )
            if found:
                array_start = next_start
                continue
            if (
                is_overflow_default_bitmap(tick_current, tick_spacing)
                and tick_spacing < 15
            ):
                raise ClmmCaptureError(
                    "BLOCKED(TICK_ARRAY_BITMAP_EXTENSION_NOT_MIRRORED)"
                )
            raise ClmmCaptureError("BLOCKED(INSUFFICIENT_LIQUIDITY_FOR_DIRECTION)")

        if not MIN_TICK <= target_tick <= MAX_TICK:
            raise ClmmCaptureError("initialized tick outside pinned bounds")
        sqrt_target = get_sqrt_price_at_tick(target_tick)
        if sqrt_target == sqrt_current:
            # Standing exactly on the boundary tick: cross it as a zero-width
            # step (no input consumed), then continue below/above it.
            tick = tick_array.ticks[(target_tick - array_start) // tick_spacing]
            liquidity = _cross_liquidity(liquidity, tick.liquidity_net, zero_for_one)
            tick_current = target_tick - 1 if zero_for_one else target_tick
            crossings += 1
            if tick_current < MIN_TICK and remaining > 0:
                raise ClmmCaptureError(
                    "BLOCKED(INSUFFICIENT_LIQUIDITY_FOR_DIRECTION): price below "
                    "MIN_TICK with input remaining"
                )
            array_start = array_start_index(tick_current, tick_spacing)
            continue
        step = compute_swap_step(
            sqrt_current,
            sqrt_target,
            liquidity,
            remaining,
            fee_rate,
            zero_for_one=zero_for_one,
            is_fee_on_input=fee_on_input,
        )
        consumed = step.amount_in + step.fee_amount if fee_on_input else step.amount_in
        if consumed > remaining:
            raise ClmmCaptureError("swap step consumed more than remaining input")
        remaining -= consumed
        total_out = _bounded_u64(total_out + step.amount_out, "cumulative output")
        total_fee = _bounded_u64(total_fee + step.fee_amount, "cumulative fee")
        sqrt_current = step.sqrt_price_next_x64
        if remaining > 0:
            if step.sqrt_price_next_x64 != sqrt_target:
                raise ClmmCaptureError("input remains without reaching the boundary")
            net = tick_array.ticks[
                (target_tick - array_start) // tick_spacing
            ].liquidity_net
            liquidity = _cross_liquidity(liquidity, net, zero_for_one)
            tick_current = target_tick - 1 if zero_for_one else target_tick
            crossings += 1
            if tick_current < MIN_TICK and remaining > 0:
                raise ClmmCaptureError(
                    "BLOCKED(INSUFFICIENT_LIQUIDITY_FOR_DIRECTION): price below "
                    "MIN_TICK with input remaining"
                )
            array_start = array_start_index(tick_current, tick_spacing)

    protocol, fund, lp = _fee_split(total_fee, config)
    return ClmmExactInQuote(
        amount_in,
        remaining,
        total_out,
        total_fee,
        protocol,
        fund,
        lp,
        zero_for_one,
        sqrt_current,
        liquidity,
        tick_current,
        crossings,
        tuple(arrays_used),
        fee_on_input,
        MATH_PROVENANCE,
    )
