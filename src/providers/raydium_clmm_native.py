"""Strict Raydium CLMM pool/tick-array decoding and exact-in swap math.

Layouts and algorithms are pinned to the vendored Apache-2.0 snapshots under
``docs/integrations/offline/solana-p0/vendor-reference/raydium/clmm/`` (upstream
commit ``6d7a0f82d2f293c553c69aaf943377367c6c4cc6``, blob-verified by
``verify_offline_bundle.py``). This module decodes evidence and computes
amount-specific quotes from complete account sets; it is a decoder, not a
capture envelope. Fail-closed by contract: Token-2022 mints, bitmap-extension
ranges, uninitialized/absent tick arrays, zero active liquidity, disabled
statuses, v2 seed layouts and any account/byte incoherence are rejected and
never quoted through.

Documented derivations (differential-tested against the vendored formulas):
- ``_delta_amount_1`` (token1 per sqrt-price interval) follows from the pinned
  liquidity definition used verbatim in ``_delta_amount_0``
  (``liquidity << 64`` divided by both sqrt prices); the token1 side is the
  direct product ``liquidity * delta >> 64``.
- ``_next_sqrt_price_from_input`` is the algebraic inverse of the pinned delta
  formulas with Uniswap-style rounding (ceil for input-driven price moves);
  the identity "amount == delta(current, target) lands exactly on target" is
  asserted in tests for both directions.
- Fee accounting (input/output variants, target vs partial step) is ported
  verbatim from ``swap_math.rs.txt`` including the ``amount_in + fee ==
  amount_remaining`` invariant and the fee-on-output dust fix.
- TickArrayBitmapExtension traversal (``tickarray_bitmap_extension.rs.txt``):
  bitmap offsets, positive/negative 512-bit slot bitmaps and the
  next-initialized-array search are ported verbatim and differential-tested
  against the Rust unit vectors.
- Dynamic fee (``pool_fee.rs.txt`` + the dynamic-fee sections of
  ``swap.rs.txt``): 80-byte ``DynamicFeeInfo`` decode/validation,
  ``tick_spacing_index_from_tick`` (Python floor division matches the pinned
  truncate-then-decrement rule), ``update_reference``, ``update_volatility_
  accumulator``, the quadratic ``compute_dynamic_fee_rate`` with ceiling
  division, ``is_fee_on_input`` for fee_on 0/1/2, and the per-step loop
  semantics (spacing-bounded target price, ``update_dynamic_fee_index``).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib

from solders.pubkey import Pubkey

from src.providers.raydium_cpmm_native import NativeAccount, NativeCaptureError

RAYDIUM_CLMM_PROGRAM_ID = "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"
CLMM_PROGRAM = Pubkey.from_string(RAYDIUM_CLMM_PROGRAM_ID)
CLMM_DECODER_REVISION = "raydium-clmm-state.v1"
CLMM_SOURCE_REVISION = "6d7a0f82d2f293c553c69aaf943377367c6c4cc6"
SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

POOL_STATE_LEN = 1544
TICK_ARRAY_STATE_LEN = 10240
TICK_ARRAY_SIZE = 60
TICK_STATE_LEN = 168
AMM_CONFIG_LEN = 117
FEE_RATE_DENOMINATOR = 1_000_000
SWAP_STATUS_BIT = 4
STATUS_OPEN_BIT = 0
MIN_TICK = -443636
MAX_TICK = 443636
MIN_SQRT_PRICE_X64 = 4295048016
MAX_SQRT_PRICE_X64 = 79226673521066979257578248091
Q64 = 1 << 64
U128_MAX = (1 << 128) - 1
U64_MAX = (1 << 64) - 1
BIT_PRECISION = 16
TICK_ARRAY_BITMAP_SIZE = 512
TRAVERSAL_STEP_LIMIT = 100_000
# --- TickArrayBitmapExtension (tickarray_bitmap_extension.rs.txt) ---
EXTENSION_TICKARRAY_BITMAP_SIZE = 14
TICK_ARRAY_BITMAP_EXTENSION_LEN = 8 + 32 + 64 * EXTENSION_TICKARRAY_BITMAP_SIZE * 2
POOL_TICK_ARRAY_BITMAP_SEED = b"pool_tick_array_bitmap_extension"
# --- Dynamic fee (pool_fee.rs.txt / dynamic_fee_config.rs.txt) ---
MAX_FEE_RATE_NUMERATOR = 100_000
VOLATILITY_ACCUMULATOR_SCALE = 10_000
REDUCTION_FACTOR_DENOMINATOR = 10_000
DYNAMIC_FEE_CONTROL_DENOMINATOR = 100_000
DYNAMIC_FEE_CONFIG_LEN = 8 + 2 + 2 + 2 + 2 + 4 + 4 + 64  # 92
DYNAMIC_FEE_CONFIG_SEED = b"dynamic_fee_config"
# Magic multipliers 2^64 / 1.0001^(2^(i-1)) for i = 1..18 (tick_math.rs.txt).
_MAGIC = (
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
    0x09AA508B5B85A500,
    0x05D6AF8DEDC582C,
    0x2216E584F5FA,
)


def _u(data: bytes, offset: int, size: int = 8) -> int:
    return int.from_bytes(data[offset : offset + size], "little")


def _i(data: bytes, offset: int, size: int = 4) -> int:
    return int.from_bytes(data[offset : offset + size], "little", signed=True)


def _pk(data: bytes, offset: int) -> str:
    return str(Pubkey.from_bytes(data[offset : offset + 32]))


def _layout(data: bytes, length: int, name: str) -> None:
    if (
        len(data) != length
        or data[:8] != hashlib.sha256(f"account:{name}".encode()).digest()[:8]
    ):
        raise NativeCaptureError(f"unsupported {name} layout/discriminator")


@dataclass(frozen=True, slots=True)
class ClmmPoolState:
    address: str
    amm_config: str
    owner: str
    token_mint_0: str
    token_mint_1: str
    token_vault_0: str
    token_vault_1: str
    observation_key: str
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
    open_time: int
    recent_epoch: int
    tick_array_bitmap: int
    dynamic_fee_raw: bytes

    @property
    def swap_enabled(self) -> bool:
        # A set bit disables the capability; bit 4 is Swap. status == 0 (all
        # bits clear) is the fully enabled pool.
        return (self.status >> SWAP_STATUS_BIT) & 1 == 0


def decode_clmm_pool_state(account: NativeAccount) -> ClmmPoolState:
    data = account.require(RAYDIUM_CLMM_PROGRAM_ID)
    _layout(data, POOL_STATE_LEN, "PoolState")
    if data[391:393] != b"\x00\x00":
        # create_customizable_pool_v2 seed indices are an unsupported layout
        # generation for this decoder revision.
        raise NativeCaptureError("unsupported CLMM pool seed_index layout")
    bitmap = 0
    for word in range(16):
        bitmap |= _u(data, 904 + 8 * word) << (64 * word)
    return ClmmPoolState(
        account.address,
        _pk(data, 9),
        _pk(data, 41),
        _pk(data, 73),
        _pk(data, 105),
        _pk(data, 137),
        _pk(data, 169),
        _pk(data, 201),
        data[233],
        data[234],
        _u(data, 235, 2),
        _u(data, 237, 16),
        _u(data, 253, 16),
        _i(data, 269),
        _u(data, 277, 16),
        _u(data, 293, 16),
        _u(data, 309),
        _u(data, 317),
        data[389],
        data[390],
        _u(data, 1080),
        _u(data, 1088),
        bitmap,
        bytes(data[1096:1176]),
    )


def clmm_vault_pda(pool: str, mint: str) -> str:
    vault, _ = Pubkey.find_program_address(
        [
            b"pool_vault",
            bytes(Pubkey.from_string(pool)),
            bytes(Pubkey.from_string(mint)),
        ],
        CLMM_PROGRAM,
    )
    return str(vault)


def tick_array_start_index(tick: int, tick_spacing: int) -> int:
    """Pinned TickArrayState::get_array_start_index.

    Rust truncates toward zero and then decrements once for negative
    non-divisible ticks, which is exactly Python floor division; no extra
    subtraction is applied.
    """
    ticks_in_array = TICK_ARRAY_SIZE * tick_spacing
    return (tick // ticks_in_array) * ticks_in_array


def clmm_tick_array_pda(pool: str, start_tick_index: int) -> str:
    address, _ = Pubkey.find_program_address(
        [
            b"tick_array",
            bytes(Pubkey.from_string(pool)),
            start_tick_index.to_bytes(4, "big", signed=True),
        ],
        CLMM_PROGRAM,
    )
    return str(address)


@dataclass(frozen=True, slots=True)
class ClmmTickState:
    tick: int
    liquidity_net: int
    liquidity_gross: int
    fee_growth_outside_0_x64: int
    fee_growth_outside_1_x64: int
    orders_amount: int = 0
    part_filled_orders_remaining: int = 0

    @property
    def initialized(self) -> bool:
        # Pinned: liquidity_gross > 0 || orders_amount > 0 || remaining > 0.
        return (
            self.liquidity_gross > 0
            or self.orders_amount > 0
            or self.part_filled_orders_remaining > 0
        )


@dataclass(frozen=True, slots=True)
class ClmmTickArray:
    address: str
    pool_id: str
    start_tick_index: int
    ticks: tuple[ClmmTickState, ...]
    initialized_tick_count: int

    def initialized_ticks(self) -> tuple[ClmmTickState, ...]:
        return tuple(t for t in self.ticks if t.initialized)


def decode_clmm_tick_array(
    account: NativeAccount, *, expected_pool: str, expected_start: int
) -> ClmmTickArray:
    data = account.require(RAYDIUM_CLMM_PROGRAM_ID)
    _layout(data, TICK_ARRAY_STATE_LEN, "TickArrayState")
    pool_id = _pk(data, 8)
    start = _i(data, 40)
    if pool_id != expected_pool or start != expected_start:
        raise NativeCaptureError("tick array pool/start binding mismatch")
    ticks = []
    for slot in range(TICK_ARRAY_SIZE):
        base = 44 + TICK_STATE_LEN * slot
        ticks.append(
            ClmmTickState(
                _i(data, base),
                _i(data, base + 4, 16),
                _u(data, base + 20, 16),
                _u(data, base + 36, 16),
                _u(data, base + 52, 16),
                _u(data, base + 124),
                _u(data, base + 132),
            )
        )
    return ClmmTickArray(account.address, pool_id, start, tuple(ticks), data[10124])


@dataclass(frozen=True, slots=True)
class ClmmAmmConfig:
    address: str
    owner: str
    protocol_fee_rate: int
    trade_fee_rate: int
    tick_spacing: int
    fund_fee_rate: int


def decode_clmm_amm_config(account: NativeAccount) -> ClmmAmmConfig:
    data = account.require(RAYDIUM_CLMM_PROGRAM_ID)
    _layout(data, AMM_CONFIG_LEN, "AmmConfig")
    return ClmmAmmConfig(
        account.address,
        _pk(data, 11),
        _u(data, 43, 4),
        _u(data, 47, 4),
        _u(data, 51, 2),
        _u(data, 53, 4),
    )


@dataclass(frozen=True, slots=True)
class ClmmTickArrayBitmapExtension:
    address: str
    pool_id: str
    positive_bitmap: tuple[int, ...]
    negative_bitmap: tuple[int, ...]


def clmm_bitmap_extension_pda(pool: str) -> str:
    address, _ = Pubkey.find_program_address(
        [POOL_TICK_ARRAY_BITMAP_SEED, bytes(Pubkey.from_string(pool))],
        CLMM_PROGRAM,
    )
    return str(address)


def decode_clmm_bitmap_extension(
    account: NativeAccount, *, expected_pool: str
) -> ClmmTickArrayBitmapExtension:
    data = account.require(RAYDIUM_CLMM_PROGRAM_ID)
    _layout(data, TICK_ARRAY_BITMAP_EXTENSION_LEN, "TickArrayBitmapExtension")
    pool_id = _pk(data, 8)
    if pool_id != expected_pool:
        raise NativeCaptureError("bitmap extension pool binding mismatch")
    if account.address != clmm_bitmap_extension_pda(expected_pool):
        raise NativeCaptureError("bitmap extension PDA mismatch")
    positive = tuple(
        int.from_bytes(data[40 + 64 * slot : 104 + 64 * slot], "little")
        for slot in range(EXTENSION_TICKARRAY_BITMAP_SIZE)
    )
    negative = tuple(
        int.from_bytes(data[488 + 64 * slot : 552 + 64 * slot], "little")
        for slot in range(EXTENSION_TICKARRAY_BITMAP_SIZE)
    )
    return ClmmTickArrayBitmapExtension(account.address, pool_id, positive, negative)


def _max_tick_in_bitmap(tick_spacing: int) -> int:
    """Pinned max_tick_in_tickarray_bitmap (tick_array_bit_map.rs.txt)."""
    return tick_spacing * TICK_ARRAY_SIZE * TICK_ARRAY_BITMAP_SIZE


def _extension_bitmap_offset(tick: int, tick_spacing: int) -> int:
    """Pinned get_bitmap_offset; only ticks outside the in-pool bitmap reach it.

    Start-index validity (Rust ``check_is_valid_start_index``) is asymmetric:
    the maximum array start is strictly below MAX_TICK, while the minimum
    array start lands exactly on ``tick_array_start_index(MIN_TICK)``.
    """
    if (
        not tick_array_start_index(MIN_TICK, tick_spacing)
        <= tick
        <= tick_array_start_index(MAX_TICK, tick_spacing)
    ):
        raise NativeCaptureError("CLMM tick outside pinned range")
    boundary = _max_tick_in_bitmap(tick_spacing)
    if -boundary <= tick < boundary:
        raise NativeCaptureError("CLMM tick inside in-pool bitmap boundary")
    offset = abs(tick) // boundary - 1
    if tick < 0 and abs(tick) % boundary == 0:
        offset -= 1
    if not 0 <= offset < EXTENSION_TICKARRAY_BITMAP_SIZE:
        raise NativeCaptureError("CLMM bitmap extension offset out of range")
    return offset


def _extension_array_offset_in_bitmap(start_index: int, tick_spacing: int) -> int:
    """Pinned tick_array_offset_in_bitmap."""
    boundary = _max_tick_in_bitmap(tick_spacing)
    m = abs(start_index) % boundary
    offset = m // (TICK_ARRAY_SIZE * tick_spacing)
    if start_index < 0 and m != 0:
        offset = TICK_ARRAY_BITMAP_SIZE - offset
    return offset


def extension_array_initialized(
    extension: ClmmTickArrayBitmapExtension, start_index: int, tick_spacing: int
) -> bool:
    offset = _extension_bitmap_offset(start_index, tick_spacing)
    bitmap = (
        extension.negative_bitmap[offset]
        if start_index < 0
        else extension.positive_bitmap[offset]
    )
    bit = _extension_array_offset_in_bitmap(start_index, tick_spacing)
    return (bitmap >> bit) & 1 == 1


def extension_next_array_start(
    extension: ClmmTickArrayBitmapExtension,
    last_start: int,
    tick_spacing: int,
    *,
    zero_for_one: bool,
) -> tuple[bool, int]:
    """Pinned next_initialized_tick_array_from_one_bitmap (verbatim port)."""
    multiplier = TICK_ARRAY_SIZE * tick_spacing
    next_start = last_start - multiplier if zero_for_one else last_start + multiplier
    min_array_start = tick_array_start_index(MIN_TICK, tick_spacing)
    max_array_start = tick_array_start_index(MAX_TICK, tick_spacing)
    if next_start < min_array_start or next_start > max_array_start:
        return False, next_start
    offset = _extension_bitmap_offset(next_start, tick_spacing)
    bitmap = (
        extension.negative_bitmap[offset]
        if next_start < 0
        else extension.positive_bitmap[offset]
    )
    bit = _extension_array_offset_in_bitmap(next_start, tick_spacing)
    boundary = _max_tick_in_bitmap(tick_spacing)
    # get_bitmap_tick_boundary for the bitmap holding next_start.
    m = abs(next_start) // boundary
    if next_start < 0 and abs(next_start) % boundary != 0:
        m += 1
    bitmap_min = -boundary * m if next_start < 0 else boundary * m
    bitmap_max = bitmap_min + boundary
    if zero_for_one:
        # U512 semantics: bits shifted past the register width are dropped.
        shifted = (bitmap << (TICK_ARRAY_BITMAP_SIZE - 1 - bit)) & ((1 << 512) - 1)
        if shifted == 0:
            return False, bitmap_min
        # next_bit is the pinned leading-zero count of the shifted 512-bit value.
        next_bit = TICK_ARRAY_BITMAP_SIZE - 1 - (shifted.bit_length() - 1)
        return True, next_start - next_bit * multiplier
    shifted = bitmap >> bit
    if shifted == 0:
        return False, bitmap_max - multiplier
    next_bit = (shifted & -shifted).bit_length() - 1  # trailing zeros
    return True, next_start + next_bit * multiplier


@dataclass(frozen=True, slots=True)
class ClmmDynamicFeeInfo:
    """80-byte DynamicFeeInfo (pool_fee.rs.txt) inside PoolState."""

    filter_period: int
    decay_period: int
    reduction_factor: int
    dynamic_fee_control: int
    max_volatility_accumulator: int
    tick_spacing_index_reference: int
    volatility_reference: int
    volatility_accumulator: int
    last_update_timestamp: int


def decode_clmm_dynamic_fee_info(raw: bytes) -> ClmmDynamicFeeInfo | None:
    if len(raw) != 80:
        raise NativeCaptureError("DynamicFeeInfo field length mismatch")
    if raw == bytes(80):
        return None  # get_dynamic_fee_info() -> None: dynamic fee disabled
    if raw[34:80] != bytes(46):
        raise NativeCaptureError("unsupported DynamicFeeInfo padding")
    return ClmmDynamicFeeInfo(
        _u(raw, 0, 2),
        _u(raw, 2, 2),
        _u(raw, 4, 2),
        _u(raw, 6, 4),
        _u(raw, 10, 4),
        _i(raw, 14),
        _u(raw, 18, 4),
        _u(raw, 22, 4),
        _u(raw, 26, 8),
    )


@dataclass(frozen=True, slots=True)
class ClmmDynamicFeeConfig:
    address: str
    index: int
    filter_period: int
    decay_period: int
    reduction_factor: int
    dynamic_fee_control: int
    max_volatility_accumulator: int


def decode_clmm_dynamic_fee_config(account: NativeAccount) -> ClmmDynamicFeeConfig:
    data = account.require(RAYDIUM_CLMM_PROGRAM_ID)
    _layout(data, DYNAMIC_FEE_CONFIG_LEN, "DynamicFeeConfig")
    if data[24:88] != bytes(64):
        raise NativeCaptureError("unsupported DynamicFeeConfig padding")
    return ClmmDynamicFeeConfig(
        account.address,
        _u(data, 8, 2),
        _u(data, 10, 2),
        _u(data, 12, 2),
        _u(data, 14, 2),
        _u(data, 16, 4),
        _u(data, 20, 4),
    )


def validate_dynamic_fee_params(info: ClmmDynamicFeeInfo, tick_spacing: int) -> None:
    """Pinned DynamicFeeInfo::validate_params (typed rejections)."""
    if info.filter_period == 0:
        raise NativeCaptureError("CLMM dynamic fee filter_period is zero")
    if info.decay_period == 0 or info.decay_period <= info.filter_period:
        raise NativeCaptureError("CLMM dynamic fee decay_period invalid")
    if (
        info.reduction_factor == 0
        or info.reduction_factor >= REDUCTION_FACTOR_DENOMINATOR
    ):
        raise NativeCaptureError("CLMM dynamic fee reduction_factor invalid")
    if (
        info.dynamic_fee_control == 0
        or info.dynamic_fee_control >= DYNAMIC_FEE_CONTROL_DENOMINATOR
    ):
        raise NativeCaptureError("CLMM dynamic fee control invalid")
    if info.max_volatility_accumulator * tick_spacing > 0xFFFFFFFF:
        raise NativeCaptureError("CLMM dynamic fee max volatility overflow")


def tick_spacing_index_from_tick(tick: int, tick_spacing: int) -> int:
    """Pinned tick_spacing_index_from_tick (floor semantics verified in Rust)."""
    return tick // tick_spacing


def dynamic_fee_update_reference(
    info: ClmmDynamicFeeInfo, tick_spacing_index: int, current_timestamp: int
) -> ClmmDynamicFeeInfo:
    """Pinned DynamicFeeInfo::update_reference."""
    elapsed = max(0, current_timestamp - info.last_update_timestamp)
    if elapsed < info.filter_period:
        return info
    if elapsed < info.decay_period:
        decayed = (
            info.volatility_accumulator
            * info.reduction_factor
            // REDUCTION_FACTOR_DENOMINATOR
        )
        return replace(
            info,
            tick_spacing_index_reference=tick_spacing_index,
            volatility_reference=decayed,
            last_update_timestamp=current_timestamp,
        )
    return replace(
        info,
        tick_spacing_index_reference=tick_spacing_index,
        volatility_reference=0,
        last_update_timestamp=current_timestamp,
    )


def dynamic_fee_update_volatility_accumulator(
    info: ClmmDynamicFeeInfo, tick_spacing_index: int
) -> ClmmDynamicFeeInfo:
    """Pinned DynamicFeeInfo::update_volatility_accumulator."""
    delta = abs(info.tick_spacing_index_reference - tick_spacing_index)
    accumulator = info.volatility_reference + delta * VOLATILITY_ACCUMULATOR_SCALE
    clamped = min(accumulator, info.max_volatility_accumulator)
    return replace(info, volatility_accumulator=clamped)


def compute_dynamic_fee_rate(info: ClmmDynamicFeeInfo, tick_spacing: int) -> int:
    """Pinned SwapState::compute_dynamic_fee_rate (quadratic, ceiling division)."""
    crossed = info.volatility_accumulator * tick_spacing
    squared = crossed * crossed
    denominator = DYNAMIC_FEE_CONTROL_DENOMINATOR * VOLATILITY_ACCUMULATOR_SCALE**2
    fee_rate = _mul_div_ceil(info.dynamic_fee_control, squared, denominator)
    if fee_rate > MAX_FEE_RATE_NUMERATOR:
        return MAX_FEE_RATE_NUMERATOR
    return fee_rate


def sqrt_price_at_tick(tick: int) -> int:
    """Pinned tick -> sqrt price (Q64.64) bit-by-bit computation."""
    if not MIN_TICK <= tick <= MAX_TICK:
        raise NativeCaptureError("tick outside pinned CLMM range")
    abs_tick = abs(tick)
    ratio = 0xFFFCB933BD6FB800 if abs_tick & 0x1 else Q64
    for index, magic in enumerate(_MAGIC):
        if abs_tick & (1 << (index + 1)):
            ratio = ratio * magic >> 64
    if tick > 0:
        ratio = U128_MAX // ratio
    return ratio


def tick_at_sqrt_price(sqrt_price_x64: int) -> int:
    """Pinned inverse: greatest tick with sqrt_price_at_tick(tick) <= price."""
    if not MIN_SQRT_PRICE_X64 <= sqrt_price_x64 < MAX_SQRT_PRICE_X64:
        raise NativeCaptureError("sqrt price outside pinned CLMM range")
    msb = sqrt_price_x64.bit_length() - 1
    log2p_integer_x32 = (msb - 64) << 32
    bit = 0x8000_0000_0000_0000
    precision = 0
    log2p_fraction_x64 = 0
    r = sqrt_price_x64 >> (msb - 63) if msb >= 64 else sqrt_price_x64 << (63 - msb)
    while bit > 0 and precision < BIT_PRECISION:
        r *= r
        is_r_more_than_two = r >> 127
        r >>= 63 + is_r_more_than_two
        log2p_fraction_x64 += bit * is_r_more_than_two
        bit >>= 1
        precision += 1
    log2p_x32 = log2p_integer_x32 + (log2p_fraction_x64 >> 32)
    log_sqrt_10001_x64 = log2p_x32 * 59543866431248
    tick_low = (log_sqrt_10001_x64 - 184467440737095516) >> 64
    tick_high = (log_sqrt_10001_x64 + 15793534762490258745) >> 64
    if tick_low == tick_high:
        return tick_low
    if sqrt_price_at_tick(tick_high) <= sqrt_price_x64:
        return tick_high
    return tick_low


def _mul_div_floor(a: int, b: int, denominator: int) -> int:
    if denominator == 0:
        raise NativeCaptureError("division by zero in CLMM math")
    return a * b // denominator


def _mul_div_ceil(a: int, b: int, denominator: int) -> int:
    if denominator == 0:
        raise NativeCaptureError("division by zero in CLMM math")
    quotient, remainder = divmod(a * b, denominator)
    return quotient + (1 if remainder else 0)


def _delta_amount_0(sqrt_a: int, sqrt_b: int, liquidity: int, *, round_up: bool) -> int:
    """Pinned get_delta_amount_0_unsigned (token0 per sqrt-price interval)."""
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    if sqrt_a <= 0:
        raise NativeCaptureError("zero sqrt price in CLMM delta")
    numerator_1 = liquidity << 64
    numerator_2 = sqrt_b - sqrt_a
    if round_up:
        result = _mul_div_ceil(
            _mul_div_ceil(numerator_1, numerator_2, sqrt_b), 1, sqrt_a
        )
    else:
        result = _mul_div_floor(numerator_1, numerator_2, sqrt_b) // sqrt_a
    if result > U64_MAX:
        raise NativeCaptureError("CLMM MaxTokenOverflow at target")
    return result


def _delta_amount_1(sqrt_a: int, sqrt_b: int, liquidity: int, *, round_up: bool) -> int:
    """token1 per sqrt-price interval: liquidity * delta / 2^64 (derived)."""
    if sqrt_b < sqrt_a:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    result = (
        _mul_div_ceil(liquidity, sqrt_b - sqrt_a, Q64)
        if round_up
        else (liquidity * (sqrt_b - sqrt_a) >> 64)
    )
    if result > U64_MAX:
        raise NativeCaptureError("CLMM MaxTokenOverflow at target")
    return result


def _next_sqrt_price_from_input(
    sqrt_price: int, liquidity: int, amount: int, *, zero_for_one: bool
) -> int:
    """Algebraic inverse of the pinned delta formulas (exact-in partial step).

    Rounding matches the Uniswap-V3 library the pinned program forks:
    amount0-driven price moves round the result up, amount1-driven moves add
    a ceiled delta. ``compute_swap`` re-derives the consumed amount from the
    returned price, so this value only needs the pinned direction/bounds.
    """
    if liquidity <= 0 or sqrt_price <= 0:
        raise NativeCaptureError("degenerate CLMM price step")
    if zero_for_one:
        # delta_0(current, next) == amount
        # => next = L*Q64*sqrt / (L*Q64 + amount*sqrt)  (price moves down)
        # The product stays exact (unbounded ints); only the final division
        # rounds, matching the Uniswap library this program forks.
        numerator = liquidity * Q64
        denominator = numerator + amount * sqrt_price
        if denominator < numerator:
            raise NativeCaptureError("CLMM price step overflow")
        return _mul_div_ceil(numerator, sqrt_price, denominator)
    # delta_1(current, next) == amount  =>  next = sqrt + ceil(amount*Q64 / L)
    return sqrt_price + _mul_div_ceil(amount, Q64, liquidity)


def _compute_swap_step(
    sqrt_price_current: int,
    sqrt_price_target: int,
    liquidity: int,
    amount_remaining: int,
    fee_rate: int,
    *,
    zero_for_one: bool,
    is_fee_on_input: bool,
):
    """Pinned compute_swap for exact-in swaps (fee rules ported verbatim)."""
    if not 0 <= fee_rate < FEE_RATE_DENOMINATOR:
        raise NativeCaptureError("CLMM fee rate out of pinned range")
    if is_fee_on_input:
        amount_for_price_calc = _mul_div_floor(
            amount_remaining, FEE_RATE_DENOMINATOR - fee_rate, FEE_RATE_DENOMINATOR
        )
    else:
        amount_for_price_calc = amount_remaining
    try:
        if zero_for_one:
            target_amount = _delta_amount_0(
                sqrt_price_target, sqrt_price_current, liquidity, round_up=True
            )
        else:
            target_amount = _delta_amount_1(
                sqrt_price_current, sqrt_price_target, liquidity, round_up=True
            )
    except NativeCaptureError as exc:
        # Pinned behavior: a u64-overflowing target delta falls through to
        # the from-input price computation instead of reverting the step.
        if "MaxTokenOverflow" not in str(exc):
            raise
        target_amount = None
    if target_amount is not None and amount_for_price_calc >= target_amount:
        sqrt_next = sqrt_price_target
        if zero_for_one:
            amount_in = _delta_amount_0(
                sqrt_price_target, sqrt_price_current, liquidity, round_up=True
            )
            amount_out = _delta_amount_1(
                sqrt_price_target, sqrt_price_current, liquidity, round_up=False
            )
        else:
            amount_in = _delta_amount_1(
                sqrt_price_current, sqrt_price_target, liquidity, round_up=True
            )
            amount_out = _delta_amount_0(
                sqrt_price_current, sqrt_price_target, liquidity, round_up=False
            )
    else:
        sqrt_next = _next_sqrt_price_from_input(
            sqrt_price_current,
            liquidity,
            amount_for_price_calc,
            zero_for_one=zero_for_one,
        )
        if zero_for_one:
            amount_in = _delta_amount_0(
                sqrt_next, sqrt_price_current, liquidity, round_up=True
            )
            amount_out = _delta_amount_1(
                sqrt_next, sqrt_price_current, liquidity, round_up=False
            )
        else:
            amount_in = _delta_amount_1(
                sqrt_price_current, sqrt_next, liquidity, round_up=True
            )
            amount_out = _delta_amount_0(
                sqrt_price_current, sqrt_next, liquidity, round_up=False
            )
    if is_fee_on_input:
        if sqrt_next != sqrt_price_target:
            fee_amount = amount_remaining - amount_in
            # Partial step: the input splits exactly into consumed + fee.
            if amount_in + fee_amount != amount_remaining:
                raise NativeCaptureError("CLMM fee/input invariant violated")
        else:
            # Target reached: leftover input belongs to the next traversal
            # step, so the pinned fee formula applies instead.
            fee_amount = _mul_div_ceil(
                amount_in, fee_rate, FEE_RATE_DENOMINATOR - fee_rate
            )
    else:
        fee_amount = _mul_div_ceil(amount_out, fee_rate, FEE_RATE_DENOMINATOR)
        amount_out -= fee_amount
        if sqrt_next != sqrt_price_target:
            # Pinned dust fix: a partial fee-on-output step consumes the full input.
            amount_in = amount_remaining
    if amount_out > U64_MAX or amount_in > U64_MAX:
        raise NativeCaptureError("CLMM MaxTokenOverflow in step")
    return sqrt_next, amount_in, amount_out, fee_amount


def _bitmap_bit(pool: ClmmPoolState, start_index: int) -> int:
    ticks_in_array = TICK_ARRAY_SIZE * pool.tick_spacing
    if start_index % ticks_in_array != 0:
        raise NativeCaptureError("tick array start index misaligned")
    compressed = start_index // ticks_in_array
    bit = compressed + TICK_ARRAY_BITMAP_SIZE
    if not 0 <= bit < 1024:
        raise NativeCaptureError("CLMM_TICK_ARRAY_BITMAP_EXTENSION_REQUIRED")
    return bit


def _bitmap_has(pool: ClmmPoolState, start_index: int) -> bool:
    return (pool.tick_array_bitmap >> _bitmap_bit(pool, start_index)) & 1 == 1


def _next_initialized_array_start(
    pool: ClmmPoolState, from_start: int, *, zero_for_one: bool
) -> int:
    ticks_in_array = TICK_ARRAY_SIZE * pool.tick_spacing
    current = _bitmap_bit(pool, from_start)
    value = pool.tick_array_bitmap
    if zero_for_one:
        masked = value & ((1 << current) - 1)
        if masked == 0:
            raise NativeCaptureError("CLMM_TICK_ARRAY_BITMAP_EXTENSION_REQUIRED")
        bit = masked.bit_length() - 1
    else:
        masked = value >> (current + 1)
        if masked == 0:
            raise NativeCaptureError("CLMM_TICK_ARRAY_BITMAP_EXTENSION_REQUIRED")
        bit = current + 1 + (masked & -masked).bit_length() - 1
    return (bit - TICK_ARRAY_BITMAP_SIZE) * ticks_in_array


def _inpool_next_array_start_pinned(
    pool: ClmmPoolState, from_start: int, *, zero_for_one: bool
) -> tuple[bool, int]:
    """Pinned tick_array_bit_map::next_initialized_tick_array_start_index.

    Returns (found, index); on miss the pinned boundary index is carried so
    the extension search can resume exactly where the pinned loop resumes.
    """
    ticks_in_array = TICK_ARRAY_SIZE * pool.tick_spacing
    boundary = ticks_in_array * TICK_ARRAY_BITMAP_SIZE
    next_start = (
        from_start - ticks_in_array if zero_for_one else from_start + ticks_in_array
    )
    if next_start < -boundary or next_start >= boundary:
        return False, from_start
    compressed = next_start // ticks_in_array + TICK_ARRAY_BITMAP_SIZE
    if next_start < 0 and next_start % ticks_in_array != 0:
        compressed -= 1
    bit_pos = abs(compressed)
    value = pool.tick_array_bitmap
    if zero_for_one:
        # U1024 semantics: bits shifted past the register width are dropped.
        shifted = (value << (1024 - bit_pos - 1)) & ((1 << 1024) - 1)
        if shifted == 0:
            return False, -boundary
        # Pinned leading-zero count of the shifted 1024-bit value.
        next_bit = 1023 - (shifted.bit_length() - 1)
        return True, (bit_pos - next_bit - TICK_ARRAY_BITMAP_SIZE) * ticks_in_array
    shifted = value >> bit_pos
    if shifted == 0:
        return False, boundary - ticks_in_array
    next_bit = (shifted & -shifted).bit_length() - 1
    return True, (bit_pos + next_bit - TICK_ARRAY_BITMAP_SIZE) * ticks_in_array


def _next_array_start_with_extension(
    pool: ClmmPoolState,
    extension: ClmmTickArrayBitmapExtension | None,
    from_start: int,
    *,
    zero_for_one: bool,
) -> tuple[bool, int]:
    """Pinned PoolState::next_tick_array_index_with_extension_info."""
    last = from_start
    while True:
        found, start = _inpool_next_array_start_pinned(
            pool, last, zero_for_one=zero_for_one
        )
        if found:
            return True, start
        if pool.tick_spacing >= 15:
            # The in-pool bitmap already spans the full pinned tick range.
            return False, start
        if extension is None:
            raise NativeCaptureError(
                "CLMM_TICK_ARRAY_BITMAP_EXTENSION_REQUIRED "
                "(extension account missing)"
            )
        last = start
        found, start = extension_next_array_start(
            extension, last, pool.tick_spacing, zero_for_one=zero_for_one
        )
        if found:
            return True, start
        last = start
        if last < MIN_TICK or last > MAX_TICK:
            return False, last


@dataclass(frozen=True, slots=True)
class ClmmQuote:
    amount_in: int
    amount_out: int
    fee_amount: int
    sqrt_price_end_x64: int
    tick_end: int
    liquidity_end: int
    crossed_ticks: tuple[int, ...]
    tick_arrays_used: tuple[str, ...]
    trade_fee_rate: int
    protocol_fee_rate: int
    decoder_revision: str = CLMM_DECODER_REVISION
    dynamic_fee_decoded: bool = False
    evidence_state: str = "VENUE_STATE_DECODED"
    dynamic_fee_rate_end: int | None = None
    volatility_accumulator_end: int | None = None
    block_timestamp: int | None = None
    bitmap_extension_used: str | None = None
    fund_fee_rate: int = 0

    @property
    def consumed_input(self) -> int:
        return self.amount_in + (self.fee_amount if self.dynamic_fee_decoded else 0)


def clmm_exact_in_quote(
    pool: ClmmPoolState,
    config: ClmmAmmConfig,
    tick_arrays: tuple[ClmmTickArray, ...],
    amount_in: int,
    *,
    zero_for_one: bool,
    bitmap_extension: ClmmTickArrayBitmapExtension | None = None,
    dynamic_fee_config: ClmmDynamicFeeConfig | None = None,
    block_timestamp: int | None = None,
) -> ClmmQuote:
    """Amount-specific exact-in quote through initialized ticks (integer math).

    Requires the complete reachable tick-array set for the walk, coherent
    pool/config/vault bindings, an enabled status and non-zero active
    liquidity. Never returns a quote from partial tick data.

    Dynamic fee: when the pool's 80-byte ``DynamicFeeInfo`` is non-zero the
    pinned fee state machine (filter/decay windows, volatility accumulator,
    quadratic dynamic fee rate, spacing-bounded step targets) is applied per
    step and ``block_timestamp`` (Unix seconds) is mandatory. Fee rates use
    the pinned numerator domain (FEE_RATE_DENOMINATOR = 1_000_000; the
    dynamic-fee constants are denominator-independent).

    Deviation note (documented, differential-tested at function level): the
    loop-level tick bookkeeping follows the existing decoder revision
    (tick == crossed boundary tick) rather than the pinned
    ``state.tick = tick_next - 1`` convention; dynamic-fee helpers are
    verbatim ports validated against the Rust unit vectors, and the per-step
    index update follows the pinned skipped/nonskipped branches using this
    decoder's tick values.
    """
    if type(amount_in) is not int or not 1 <= amount_in <= U64_MAX:
        raise NativeCaptureError("CLMM exact-in amount out of u64 range")
    if pool.tick_spacing != config.tick_spacing:
        raise NativeCaptureError("pool/config tick spacing mismatch")
    if pool.amm_config != config.address:
        raise NativeCaptureError("pool/config binding mismatch")
    if not pool.swap_enabled:
        raise NativeCaptureError("CLMM pool swap disabled by status bits")
    if pool.fee_on not in (0, 1, 2):
        raise NativeCaptureError("unsupported CLMM fee_on mode")
    if pool.liquidity == 0:
        raise NativeCaptureError("CLMM_INSUFFICIENT_ACTIVE_LIQUIDITY")
    if not MIN_TICK <= pool.tick_current <= MAX_TICK:
        raise NativeCaptureError("pool current tick outside pinned range")
    if not MIN_SQRT_PRICE_X64 <= pool.sqrt_price_x64 < MAX_SQRT_PRICE_X64:
        raise NativeCaptureError("pool sqrt price outside pinned range")
    expected_pool, _ = Pubkey.find_program_address(
        [
            b"pool",
            bytes(Pubkey.from_string(pool.amm_config)),
            bytes(Pubkey.from_string(pool.token_mint_0)),
            bytes(Pubkey.from_string(pool.token_mint_1)),
        ],
        CLMM_PROGRAM,
    )
    if pool.address != str(expected_pool):
        raise NativeCaptureError("CLMM pool PDA binding mismatch")
    if pool.token_vault_0 != clmm_vault_pda(pool.address, pool.token_mint_0):
        raise NativeCaptureError("CLMM vault0 PDA binding mismatch")
    if pool.token_vault_1 != clmm_vault_pda(pool.address, pool.token_mint_1):
        raise NativeCaptureError("CLMM vault1 PDA binding mismatch")
    if block_timestamp is not None and (
        type(block_timestamp) is not int or block_timestamp < 0
    ):
        raise NativeCaptureError("CLMM block timestamp must be a non-negative integer")
    if block_timestamp is not None and block_timestamp <= pool.open_time:
        raise NativeCaptureError("CLMM swap before pool open time")
    dynamic_fee = decode_clmm_dynamic_fee_info(pool.dynamic_fee_raw)
    if dynamic_fee is not None:
        validate_dynamic_fee_params(dynamic_fee, pool.tick_spacing)
        if type(block_timestamp) is not int:
            raise NativeCaptureError("CLMM dynamic fee requires block timestamp")
        if dynamic_fee_config is not None:
            if (
                dynamic_fee_config.filter_period != dynamic_fee.filter_period
                or dynamic_fee_config.decay_period != dynamic_fee.decay_period
                or dynamic_fee_config.reduction_factor != dynamic_fee.reduction_factor
                or dynamic_fee_config.dynamic_fee_control
                != dynamic_fee.dynamic_fee_control
                or dynamic_fee_config.max_volatility_accumulator
                != dynamic_fee.max_volatility_accumulator
            ):
                raise NativeCaptureError("CLMM dynamic fee config mismatch")
        dynamic_fee = dynamic_fee_update_reference(
            dynamic_fee,
            tick_spacing_index_from_tick(pool.tick_current, pool.tick_spacing),
            block_timestamp,
        )
    arrays: dict[int, ClmmTickArray] = {}
    for array in tick_arrays:
        if array.pool_id != pool.address:
            raise NativeCaptureError("tick array pool binding mismatch")
        if array.address != clmm_tick_array_pda(pool.address, array.start_tick_index):
            raise NativeCaptureError("tick array PDA mismatch")
        in_pool_range = True
        try:
            _bitmap_bit(pool, array.start_tick_index)
        except NativeCaptureError as exc:
            if "BITMAP_EXTENSION_REQUIRED" not in str(exc):
                raise
            in_pool_range = False
        if in_pool_range:
            if not _bitmap_has(pool, array.start_tick_index):
                raise NativeCaptureError("TICK_ARRAY_NOT_INITIALIZED_IN_BITMAP")
        else:
            if bitmap_extension is None:
                raise NativeCaptureError(
                    "CLMM_TICK_ARRAY_BITMAP_EXTENSION_REQUIRED "
                    "(extension account missing)"
                )
            if not extension_array_initialized(
                bitmap_extension, array.start_tick_index, pool.tick_spacing
            ):
                raise NativeCaptureError("TICK_ARRAY_NOT_INITIALIZED_IN_BITMAP")
        if array.start_tick_index in arrays:
            raise NativeCaptureError("duplicate tick array")
        arrays[array.start_tick_index] = array
    if not arrays:
        raise NativeCaptureError("CLMM reachable tick array set empty")
    current_array_start: int | None = tick_array_start_index(
        pool.tick_current, pool.tick_spacing
    )
    if current_array_start not in arrays:
        raise NativeCaptureError("CLMM active tick array missing")
    is_fee_on_input = pool.fee_on == 0 or (pool.fee_on == 1) == zero_for_one
    sqrt_current = pool.sqrt_price_x64
    tick = pool.tick_current
    liquidity = pool.liquidity
    total_in = 0
    total_out = 0
    total_fee = 0
    crossed: list[int] = []
    used: list[str] = []
    extension_used = False
    ts_index = 0
    if dynamic_fee is not None:
        ts_index = tick_spacing_index_from_tick(pool.tick_current, pool.tick_spacing)
    dyn_rate_end: int | None = None
    vol_acc_end: int | None = None
    for _ in range(TRAVERSAL_STEP_LIMIT):
        if total_in + (total_fee if is_fee_on_input else 0) >= amount_in:
            break
        remaining = (
            amount_in - total_in - total_fee
            if is_fee_on_input
            else amount_in - total_in
        )
        array = arrays[current_array_start]
        if array.address not in used:
            used.append(array.address)
        offset = (tick - array.start_tick_index) // pool.tick_spacing
        if not 0 <= offset < TICK_ARRAY_SIZE:
            # Transition into a neighboring array mid-walk: the pinned scan
            # starts from the array edge nearest the current tick
            # (first_initialized_tick semantics), never rejects.
            offset = 0 if offset < 0 else TICK_ARRAY_SIZE - 1
        boundary = None
        candidates = (
            range(offset, -1, -1)
            if zero_for_one
            else range(offset + 1, TICK_ARRAY_SIZE)
        )
        for slot in candidates:
            state = array.ticks[slot]
            if not state.initialized:
                continue
            if (
                zero_for_one
                and state.tick == tick
                and sqrt_current == sqrt_price_at_tick(tick)
            ):
                # The tick at the current price was already crossed; scanning
                # continues strictly below it (pinned zero_for_one scan is
                # inclusive, so the guard prevents a zero-progress step).
                continue
            boundary = state
            break
        if boundary is None:
            found, next_start = _next_array_start_with_extension(
                pool,
                bitmap_extension,
                current_array_start,
                zero_for_one=zero_for_one,
            )
            if found:
                if next_start not in arrays:
                    raise NativeCaptureError("CLMM reachable tick array missing")
                in_pool = True
                try:
                    _bitmap_bit(pool, next_start)
                except NativeCaptureError as exc:
                    if "BITMAP_EXTENSION_REQUIRED" not in str(exc):
                        raise
                    in_pool = False
                if not in_pool:
                    extension_used = True
                current_array_start = next_start
                continue
            # Pinned behavior: no further initialized tick array in the swap
            # direction is LiquidityInsufficient — the price never silently
            # drifts past the last boundary of the supplied account set.
            raise NativeCaptureError("CLMM_INSUFFICIENT_LIQUIDITY_IN_DIRECTION")
        if not MIN_TICK <= boundary.tick <= MAX_TICK:
            raise NativeCaptureError("boundary tick outside pinned range")
        sqrt_target = sqrt_price_at_tick(boundary.tick)
        if zero_for_one and sqrt_target > sqrt_current:
            raise NativeCaptureError("CLMM price direction incoherent")
        if not zero_for_one and sqrt_target < sqrt_current:
            raise NativeCaptureError("CLMM price direction incoherent")
        fee_rate = config.trade_fee_rate
        bounded_tick_opt: int | None = None
        skipped = True
        if dynamic_fee is not None:
            dynamic_fee = dynamic_fee_update_volatility_accumulator(
                dynamic_fee, ts_index
            )
            dyn_rate = compute_dynamic_fee_rate(dynamic_fee, pool.tick_spacing)
            fee_rate = min(config.trade_fee_rate + dyn_rate, MAX_FEE_RATE_NUMERATOR)
            dyn_rate_end = dyn_rate
            vol_acc_end = dynamic_fee.volatility_accumulator
            if (
                liquidity > 0
                and dynamic_fee.volatility_accumulator
                != dynamic_fee.max_volatility_accumulator
            ):
                skipped = False
                bounded_tick = (
                    ts_index * pool.tick_spacing
                    if zero_for_one
                    else (ts_index + 1) * pool.tick_spacing
                )
                bounded_tick = max(MIN_TICK, min(MAX_TICK, bounded_tick))
                bounded_price = sqrt_price_at_tick(bounded_tick)
                if zero_for_one and sqrt_target > bounded_price:
                    sqrt_target = bounded_price
                    bounded_tick_opt = bounded_tick
                elif not zero_for_one and sqrt_target < bounded_price:
                    sqrt_target = bounded_price
                    bounded_tick_opt = bounded_tick
        sqrt_next, amount_in_step, amount_out, fee = _compute_swap_step(
            sqrt_current,
            sqrt_target,
            liquidity,
            remaining,
            fee_rate,
            zero_for_one=zero_for_one,
            is_fee_on_input=is_fee_on_input,
        )
        total_in += amount_in_step
        total_out += amount_out
        total_fee += fee
        moved = sqrt_next != sqrt_current
        tick_next = bounded_tick_opt if bounded_tick_opt is not None else boundary.tick
        sqrt_current = sqrt_next
        if dynamic_fee is not None and (not moved or sqrt_current == sqrt_target):
            # Pinned update_dynamic_fee_index runs on each group crossing (or
            # no-progress step); a partial step breaks at the loop head
            # instead of advancing the volatility index.
            if skipped:
                tick_index = tick_next if not moved else tick
                idx = tick_spacing_index_from_tick(tick_index, pool.tick_spacing)
                if not zero_for_one and tick_index % pool.tick_spacing == 0:
                    idx -= 1
                ts_index = idx
                if (
                    dynamic_fee.volatility_accumulator
                    != dynamic_fee.max_volatility_accumulator
                ):
                    dynamic_fee = dynamic_fee_update_volatility_accumulator(
                        dynamic_fee, ts_index
                    )
            ts_index += -1 if zero_for_one else 1
        if moved and sqrt_current == sqrt_target:
            # The boundary was reached and crossed; a partial step leaves the
            # current tick unchanged (the price sits inside the tick range).
            tick = boundary.tick
            crossed.append(boundary.tick)
            # Crossing down ADDS liquidity_net (a range ending at this tick
            # contributes negative net below it); crossing up subtracts it.
            liquidity = (
                liquidity + boundary.liquidity_net
                if zero_for_one
                else liquidity - boundary.liquidity_net
            )
            if liquidity > U128_MAX:
                raise NativeCaptureError("CLMM liquidity overflow crossing tick")
            if liquidity == 0 and remaining > 0:
                raise NativeCaptureError("CLMM_INSUFFICIENT_ACTIVE_LIQUIDITY")
            next_start = tick_array_start_index(tick, pool.tick_spacing)
            if next_start != current_array_start:
                if next_start not in arrays:
                    raise NativeCaptureError("CLMM reachable tick array missing")
                current_array_start = next_start
    if total_in + (total_fee if is_fee_on_input else 0) < amount_in:
        raise NativeCaptureError("CLMM_TRAVERSAL_EXHAUSTED_BEFORE_AMOUNT_CONSUMED")
    return ClmmQuote(
        total_in,
        total_out,
        total_fee,
        sqrt_current,
        tick,
        liquidity,
        tuple(crossed),
        tuple(used),
        config.trade_fee_rate,
        config.protocol_fee_rate,
        dynamic_fee_decoded=dynamic_fee is not None,
        dynamic_fee_rate_end=dyn_rate_end,
        volatility_accumulator_end=vol_acc_end,
        block_timestamp=block_timestamp,
        bitmap_extension_used=(
            bitmap_extension.address if extension_used and bitmap_extension else None
        ),
        fund_fee_rate=config.fund_fee_rate,
    )
