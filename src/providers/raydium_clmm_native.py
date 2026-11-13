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
"""

from __future__ import annotations

from dataclasses import dataclass
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
    ticks_in_array = TICK_ARRAY_SIZE * tick_spacing
    start = (tick // ticks_in_array) * ticks_in_array
    if tick < 0 and tick % ticks_in_array != 0:
        start -= ticks_in_array
    return start


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


def clmm_exact_in_quote(
    pool: ClmmPoolState,
    config: ClmmAmmConfig,
    tick_arrays: tuple[ClmmTickArray, ...],
    amount_in: int,
    *,
    zero_for_one: bool,
) -> ClmmQuote:
    """Amount-specific exact-in quote through initialized ticks (integer math).

    Requires the complete reachable tick-array set for the walk, coherent
    pool/config/vault bindings, an enabled status and non-zero active
    liquidity. Never returns a quote from partial tick data.
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
    arrays: dict[int, ClmmTickArray] = {}
    for array in tick_arrays:
        if array.pool_id != pool.address:
            raise NativeCaptureError("tick array pool binding mismatch")
        if array.address != clmm_tick_array_pda(pool.address, array.start_tick_index):
            raise NativeCaptureError("tick array PDA mismatch")
        if not _bitmap_has(pool, array.start_tick_index):
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
            raise NativeCaptureError("current tick outside decoded tick array")
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
            try:
                current_array_start = _next_initialized_array_start(
                    pool, current_array_start, zero_for_one=zero_for_one
                )
            except NativeCaptureError as exc:
                if "BITMAP_EXTENSION_REQUIRED" not in str(exc):
                    raise
                current_array_start = None
            if current_array_start is not None:
                if current_array_start not in arrays:
                    raise NativeCaptureError("CLMM reachable tick array missing")
                continue
            if liquidity == 0:
                raise NativeCaptureError("CLMM_INSUFFICIENT_ACTIVE_LIQUIDITY")
            # No further initialized array inside the pinned default bitmap:
            # the price keeps moving with constant liquidity until the amount
            # is exhausted (final partial step to the pinned price extreme).
            sqrt_target = MIN_SQRT_PRICE_X64 if zero_for_one else MAX_SQRT_PRICE_X64 - 1
            sqrt_next, amount_in_step, amount_out, fee = _compute_swap_step(
                sqrt_current,
                sqrt_target,
                liquidity,
                remaining,
                config.trade_fee_rate,
                zero_for_one=zero_for_one,
                is_fee_on_input=is_fee_on_input,
            )
            total_in += amount_in_step
            total_out += amount_out
            total_fee += fee
            sqrt_current = sqrt_next
            tick = tick_at_sqrt_price(sqrt_current)
            break
        if not MIN_TICK <= boundary.tick <= MAX_TICK:
            raise NativeCaptureError("boundary tick outside pinned range")
        sqrt_target = sqrt_price_at_tick(boundary.tick)
        if zero_for_one and sqrt_target > sqrt_current:
            raise NativeCaptureError("CLMM price direction incoherent")
        if not zero_for_one and sqrt_target < sqrt_current:
            raise NativeCaptureError("CLMM price direction incoherent")
        sqrt_next, amount_in_step, amount_out, fee = _compute_swap_step(
            sqrt_current,
            sqrt_target,
            liquidity,
            remaining,
            config.trade_fee_rate,
            zero_for_one=zero_for_one,
            is_fee_on_input=is_fee_on_input,
        )
        total_in += amount_in_step
        total_out += amount_out
        total_fee += fee
        sqrt_current = sqrt_next
        if sqrt_current == sqrt_target:
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
    )
