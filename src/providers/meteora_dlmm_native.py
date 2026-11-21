"""Strict Meteora DLMM LbPair/BinArray decoding, reachable walk and exact-in quote.

Layouts and discriminators are pinned to the checked-in Anchor IDL snapshot
``docs/integrations/offline/solana-p0/vendor-reference/meteora/lb_clmm.idl.json``
(metadata 0.12.0, program ``LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo``,
blob-verified). Account byte sizes (LbPair 904, BinArray 10136) follow from
the IDL's fixed-width fields including its explicit padding tombstones.

Quote math is ported verbatim from the immutable SDK source closure pinned at
commit ``1532e540db41ac405dbf4c5bb2ddfceaa1f98ff1`` (@meteora-ag/dlmm 1.9.15,
ISC) and mirrored under ``vendor-reference/meteora/``: ``constants/index.ts``
(BASIS_POINT_MAX, SCALE_OFFSET, FEE_PRECISION, MAX_FEE_RATE, bitmap sizes),
``helpers/fee.ts`` (base/variable/total fee, fee splitting),
``helpers/bin.ts`` (getAmountIn/getAmountOut/swapExactInQuoteAtBin),
``helpers/math.ts`` (mulDiv rounding), ``dlmm/index.ts`` (swapQuote loop,
updateReference/updateVolatilityAccumulator) and ``helpers/token_2022.ts``
(transfer-fee epoch selection; transfer hooks are rejected fail-closed).
Integer math only; BN semantics (floor division, ceiling adds) are
reproduced exactly. The quote loop is bounded and never partial-fills
silently: exhausted reachable liquidity is a typed rejection unless the
caller explicitly accepts a partial-fill quote, which stays non-promotable.

Indexed liquidity never becomes executable depth here; quote evidence is
fixture/replay class until rooted live account sets are captured.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from solders.pubkey import Pubkey

from src.providers.raydium_cpmm_native import NativeAccount, NativeCaptureError

METEORA_DLMM_PROGRAM_ID = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
DLMM_PROGRAM = Pubkey.from_string(METEORA_DLMM_PROGRAM_ID)
DLMM_DECODER_REVISION = "meteora-dlmm-state.v1"
DLMM_IDL_REVISION = "0.12.0"
DLMM_IDL_COMMIT = "1532e540db41ac405dbf4c5bb2ddfceaa1f98ff1"
DLMM_QUOTE_REVISION = "meteora-dlmm-quote-sdk1532e54.v1"

LB_PAIR_LEN = 904
BIN_ARRAY_LEN = 10136
BINS_PER_BIN_ARRAY = 70
BIN_LEN = 144
SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

# --- pinned SDK constants (constants/index.ts + lb_clmm.idl.json) ---
BASIS_POINT_MAX = 10_000
SCALE_OFFSET = 64
FEE_PRECISION = 1_000_000_000
MAX_FEE_RATE = 100_000_000
BIN_ARRAY_BITMAP_SIZE = 512
EXTENSION_BINARRAY_BITMAP_SIZE = 12
LIMIT_ORDER_FEE_SHARE = 5_000
MAX_FEE_BASIS_POINTS = 10_000
U64_MAX = (1 << 64) - 1
BIN_ARRAY_BITMAP_EXTENSION_LEN = 8 + 32 + 64 * EXTENSION_BINARRAY_BITMAP_SIZE * 2
BIN_ARRAY_BITMAP_EXTENSION_SEED = b"bitmap"

# Token-2022 extension tags (spl-token-2022 ExtensionType) used by the
# pinned token_2022.ts transfer-fee path.
TL_TRANSFER_FEE_CONFIG = 12
TL_TRANSFER_HOOK = 14

PAIR_STATUS_ENABLED = 0
PAIR_TYPE_NAMES = {
    0: "Permissionless",
    1: "Permission",
    2: "CustomizablePermissionless",
    3: "PermissionlessV2",
}
FUNCTION_TYPE_NAMES = {0: "Undetermined", 1: "LiquidityMining", 2: "LimitOrder"}
COLLECT_FEE_MODE_NAMES = {0: "InputOnly", 1: "OnlyY"}


def _u(data: bytes, offset: int, size: int = 8) -> int:
    return int.from_bytes(data[offset : offset + size], "little")


def _i(data: bytes, offset: int, size: int = 8) -> int:
    return int.from_bytes(data[offset : offset + size], "little", signed=True)


def _pk(data: bytes, offset: int) -> str:
    return str(Pubkey.from_bytes(data[offset : offset + 32]))


def _layout(data: bytes, length: int, name: str, discriminator: bytes) -> None:
    if len(data) != length or data[:8] != discriminator:
        raise NativeCaptureError(f"unsupported {name} layout/discriminator")


def _anchor_discriminator(name: str) -> bytes:
    # sha256("account:<Name>")[:8]; verified byte-identical to the IDL's
    # explicit discriminator arrays for all five DLMM accounts.
    return hashlib.sha256(f"account:{name}".encode()).digest()[:8]


def token_program_for_flag(flag: int) -> str:
    # Pinned mapping (lbPair.ts): flag 0 -> SPL Token, else Token-2022.
    if flag == 0:
        return SPL_TOKEN_PROGRAM_ID
    if flag == 1:
        return TOKEN_2022_PROGRAM_ID
    raise NativeCaptureError("unsupported DLMM token program flag")


@dataclass(frozen=True, slots=True)
class LbPairState:
    address: str
    active_id: int
    bin_step: int
    status: int
    pair_type: int
    activation_type: int
    token_x_mint: str
    token_y_mint: str
    reserve_x: str
    reserve_y: str
    protocol_fee_amount_x: int
    protocol_fee_amount_y: int
    oracle: str
    bin_array_bitmap: int
    token_x_program: str
    token_y_program: str
    version: int
    base_factor: int
    base_fee_power_factor: int
    variable_fee_control: int
    max_volatility_accumulator: int
    volatility_accumulator: int
    last_updated_at: int
    filter_period: int = 0
    decay_period: int = 0
    reduction_factor: int = 0
    min_bin_id: int = 0
    max_bin_id: int = 0
    protocol_share: int = 0
    function_type: int = 0
    collect_fee_mode: int = 0
    volatility_reference: int = 0
    index_reference: int = 0
    variable_last_update_timestamp: int = 0

    @property
    def enabled(self) -> bool:
        return self.status == PAIR_STATUS_ENABLED

    @property
    def pair_type_name(self) -> str:
        return PAIR_TYPE_NAMES.get(self.pair_type, "UNKNOWN")

    @property
    def function_type_name(self) -> str:
        return FUNCTION_TYPE_NAMES.get(self.function_type, "UNKNOWN")

    @property
    def collect_fee_mode_name(self) -> str:
        return COLLECT_FEE_MODE_NAMES.get(self.collect_fee_mode, "UNKNOWN")


def decode_lb_pair(account: NativeAccount) -> LbPairState:
    data = account.require(METEORA_DLMM_PROGRAM_ID)
    _layout(data, LB_PAIR_LEN, "LbPair", _anchor_discriminator("LbPair"))
    if data[882] != 0:
        raise NativeCaptureError("unsupported DLMM LbPair version byte")
    bitmap = 0
    for word in range(16):
        bitmap |= _u(data, 584 + 8 * word) << (64 * word)
    return LbPairState(
        account.address,
        _i(data, 76, 4),
        _u(data, 80, 2),
        data[82],
        data[75],
        data[86],
        _pk(data, 88),
        _pk(data, 120),
        _pk(data, 152),
        _pk(data, 184),
        _u(data, 216),
        _u(data, 224),
        _pk(data, 552),
        bitmap,
        token_program_for_flag(data[880]),
        token_program_for_flag(data[881]),
        data[882],
        _u(data, 8, 2),  # StaticParameters.base_factor (rel 0)
        data[34],  # StaticParameters.base_fee_power_factor (rel 26)
        _u(data, 16, 4),  # StaticParameters.variable_fee_control (rel 8)
        _u(data, 20, 4),  # StaticParameters.max_volatility_accumulator (rel 12)
        _u(data, 40, 4),  # VariableParameters.volatility_accumulator (rel 32)
        _i(data, 712),
        _u(data, 10, 2),  # StaticParameters.filter_period (rel 2)
        _u(data, 12, 2),  # StaticParameters.decay_period (rel 4)
        _u(data, 14, 2),  # StaticParameters.reduction_factor (rel 6)
        _i(data, 24, 4),  # StaticParameters.min_bin_id (rel 16)
        _i(data, 28, 4),  # StaticParameters.max_bin_id (rel 20)
        _u(data, 32, 2),  # StaticParameters.protocol_share (rel 24)
        data[35],  # StaticParameters.function_type (rel 27)
        data[36],  # StaticParameters.collect_fee_mode (rel 28)
        _u(data, 44, 4),  # VariableParameters.volatility_reference (rel 4)
        _i(data, 48, 4),  # VariableParameters.index_reference (rel 8)
        _i(data, 56),  # VariableParameters.last_update_timestamp (rel 16)
    )


def base_fee_rate(lb_pair: LbPairState) -> int:
    """Pinned base fee law: base_factor * bin_step * 10 * 10^power_factor.

    The absolute fee-precision denominator lives in the SDK constants module,
    which is not vendored; the rate is reported in native units and never
    converted to a percentage here.
    """
    return (
        lb_pair.base_factor
        * lb_pair.bin_step
        * 10
        * (10**lb_pair.base_fee_power_factor)
    )


@dataclass(frozen=True, slots=True)
class DlmmBin:
    bin_id: int
    amount_x: int
    amount_y: int
    price: int
    liquidity_supply: int

    @property
    def has_liquidity(self) -> bool:
        return self.liquidity_supply > 0


@dataclass(frozen=True, slots=True)
class DlmmBinArray:
    address: str
    lb_pair: str
    index: int
    version: int
    bins: tuple[DlmmBin, ...]

    @property
    def lower_bin_id(self) -> int:
        return self.index * BINS_PER_BIN_ARRAY

    def bin(self, bin_id: int) -> DlmmBin:
        # Pinned mapping: positive ids index forward from the lower bound,
        # non-positive ids index backward from the upper bound.
        if bin_id > 0:
            offset = bin_id - self.lower_bin_id
        else:
            offset = BINS_PER_BIN_ARRAY - (
                (self.lower_bin_id + BINS_PER_BIN_ARRAY - 1 - bin_id) + 1
            )
        if not 0 <= offset < BINS_PER_BIN_ARRAY:
            raise NativeCaptureError("bin id outside decoded bin array")
        return self.bins[offset]


def decode_bin_array(account: NativeAccount, *, expected_pair: str) -> DlmmBinArray:
    data = account.require(METEORA_DLMM_PROGRAM_ID)
    _layout(data, BIN_ARRAY_LEN, "BinArray", _anchor_discriminator("BinArray"))
    pair = _pk(data, 24)
    if pair != expected_pair:
        raise NativeCaptureError("bin array lb_pair binding mismatch")
    index = _i(data, 8)
    version = data[16]
    if version != 0:
        raise NativeCaptureError("unsupported DLMM BinArray version byte")
    bins = []
    for slot in range(BINS_PER_BIN_ARRAY):
        base = 56 + BIN_LEN * slot
        bins.append(
            DlmmBin(
                _bin_id_for_slot(index, slot),
                _u(data, base),
                _u(data, base + 8),
                _u(data, base + 16, 16),
                _u(data, base + 32, 16),
            )
        )
    return DlmmBinArray(account.address, pair, index, version, tuple(bins))


def _bin_id_for_slot(index: int, slot: int) -> int:
    lower = index * BINS_PER_BIN_ARRAY
    return lower + slot


def bin_array_index_for_bin_id(bin_id: int) -> int:
    """Pinned mapping (binArray.ts binIdToBinArrayIndex).

    BN.divmod truncates toward zero; a negative bin id with a nonzero
    remainder steps one array further down. Verified cases: -1 -> -1,
    -70 -> -1, -71 -> -2, 69 -> 0, 70 -> 1.
    """
    if not type(bin_id) is int:
        raise NativeCaptureError("bin id must be an integer")
    magnitude = abs(bin_id) // BINS_PER_BIN_ARRAY
    index = -magnitude if bin_id < 0 else magnitude
    if bin_id < 0 and bin_id % BINS_PER_BIN_ARRAY != 0:
        index -= 1
    return index


@dataclass(frozen=True, slots=True)
class DlmmReachableState:
    swap_for_y: bool
    active_id: int
    reachable_bins: tuple[tuple[int, int, int], ...]
    bin_arrays_used: tuple[str, ...]
    decoder_revision: str = DLMM_DECODER_REVISION
    amount_specific_quote: str = (
        "DLMM_WALK_STATE_ONLY: amount-specific quote via " "dlmm_swap_exact_in_quote"
    )
    evidence_state: str = "VENUE_STATE_DECODED"


def dlmm_reachable_state(
    lb_pair: LbPairState,
    bin_arrays: tuple[DlmmBinArray, ...],
    *,
    swap_for_y: bool,
    max_bins: int = 70,
) -> DlmmReachableState:
    """Walk the reachable bins from the active bin in the swap direction.

    State verification only: reports per-bin (bin_id, reserve_x, reserve_y)
    for bins that still hold liquidity, following the pinned advance rule
    (``swapForY ? activeId -= 1 : activeId += 1``). No output amount is ever
    produced — see the module docstring for the missing-pin boundary.
    """
    if not isinstance(max_bins, int) or not 1 <= max_bins <= 70:
        raise NativeCaptureError("bounded reachable-bin window required")
    if not lb_pair.enabled:
        raise NativeCaptureError("DLMM pair disabled by status byte")
    arrays: dict[int, DlmmBinArray] = {}
    for array in bin_arrays:
        if array.lb_pair != lb_pair.address:
            raise NativeCaptureError("bin array pair binding mismatch")
        if array.index not in arrays:
            arrays[array.index] = array
    active_index = bin_array_index_for_bin_id(lb_pair.active_id)
    if active_index not in arrays:
        raise NativeCaptureError("DLMM active bin array missing")
    bin_id = lb_pair.active_id
    reachable: list[tuple[int, int, int]] = []
    used: list[str] = []
    for _ in range(max_bins):
        index = bin_array_index_for_bin_id(bin_id)
        if index not in arrays:
            raise NativeCaptureError("DLMM reachable bin array missing")
        array = arrays[index]
        if array.address not in used:
            used.append(array.address)
        bin_state = array.bin(bin_id)
        if bin_state.has_liquidity:
            reachable.append((bin_id, bin_state.amount_x, bin_state.amount_y))
        bin_id = bin_id - 1 if swap_for_y else bin_id + 1
    return DlmmReachableState(
        swap_for_y,
        lb_pair.active_id,
        tuple(reachable),
        tuple(used),
    )


def dlmm_amount_specific_quote(*args, **kwargs):
    """Backwards-compatible fail-closed sink.

    The exact-in quote is implemented by :func:`dlmm_swap_exact_in_quote`
    with an explicit argument contract; this legacy sink keeps rejecting so
    accidental positional callers never receive an unvalidated quote.
    """
    raise NativeCaptureError(
        "DLMM_AMOUNT_SPECIFIC_QUOTE_USE_CONTRACTED_API: call "
        "dlmm_swap_exact_in_quote(lb_pair, bin_arrays, amount_in, ...) with "
        "the full dependency set; untyped quote calls are rejected"
    )


# --- BinArrayBitmapExtension (binArray.ts derive + IDL layout) --------------


def derive_bin_array_bitmap_extension_pda(lb_pair: str) -> str:
    address, _ = Pubkey.find_program_address(
        [BIN_ARRAY_BITMAP_EXTENSION_SEED, bytes(Pubkey.from_string(lb_pair))],
        DLMM_PROGRAM,
    )
    return str(address)


@dataclass(frozen=True, slots=True)
class DlmmBinArrayBitmapExtension:
    address: str
    lb_pair: str
    positive_bitmap: tuple[int, ...]
    negative_bitmap: tuple[int, ...]


def decode_bin_array_bitmap_extension(
    account: NativeAccount, *, expected_pair: str
) -> DlmmBinArrayBitmapExtension:
    data = account.require(METEORA_DLMM_PROGRAM_ID)
    _layout(
        data,
        BIN_ARRAY_BITMAP_EXTENSION_LEN,
        "BinArrayBitmapExtension",
        _anchor_discriminator("BinArrayBitmapExtension"),
    )
    pair = _pk(data, 8)
    if pair != expected_pair:
        raise NativeCaptureError("bin array bitmap extension pair binding mismatch")
    if account.address != derive_bin_array_bitmap_extension_pda(expected_pair):
        raise NativeCaptureError("bin array bitmap extension PDA mismatch")
    positive = tuple(
        int.from_bytes(data[40 + 64 * slot : 104 + 64 * slot], "little")
        for slot in range(EXTENSION_BINARRAY_BITMAP_SIZE)
    )
    negative = tuple(
        int.from_bytes(data[760 + 64 * slot : 824 + 64 * slot], "little")
        for slot in range(EXTENSION_BINARRAY_BITMAP_SIZE)
    )
    return DlmmBinArrayBitmapExtension(account.address, pair, positive, negative)


def _extension_bitmap_parts(bin_array_index: int) -> tuple[int, int]:
    """Pinned findSetBit offsets: (bitmap_offset, bit_offset)."""
    if bin_array_index > 0:
        return (
            bin_array_index // BIN_ARRAY_BITMAP_SIZE - 1,
            bin_array_index % BIN_ARRAY_BITMAP_SIZE,
        )
    shifted = -(bin_array_index + 1)
    return shifted // BIN_ARRAY_BITMAP_SIZE - 1, shifted % BIN_ARRAY_BITMAP_SIZE


def extension_bin_array_initialized(
    extension: DlmmBinArrayBitmapExtension, bin_array_index: int
) -> bool:
    bitmap_offset, bit = _extension_bitmap_parts(bin_array_index)
    if not 0 <= bitmap_offset < EXTENSION_BINARRAY_BITMAP_SIZE:
        raise NativeCaptureError("DLMM bitmap extension offset out of range")
    bitmap = (
        extension.positive_bitmap[bitmap_offset]
        if bin_array_index > 0
        else extension.negative_bitmap[bitmap_offset]
    )
    return (bitmap >> bit) & 1 == 1


def find_next_bin_array_index_with_liquidity(
    swap_for_y: bool,
    active_bin_id: int,
    lb_pair: LbPairState,
    extension: DlmmBinArrayBitmapExtension | None,
) -> int | None:
    """Pinned findNextBinArrayIndexWithLiquidity (binArray.ts verbatim port)."""
    lower_default = -BIN_ARRAY_BITMAP_SIZE
    upper_default = BIN_ARRAY_BITMAP_SIZE - 1
    ext_min = -BIN_ARRAY_BITMAP_SIZE * (EXTENSION_BINARRAY_BITMAP_SIZE + 1)
    ext_max = BIN_ARRAY_BITMAP_SIZE * (EXTENSION_BINARRAY_BITMAP_SIZE + 1) - 1
    start = bin_array_index_for_bin_id(active_bin_id)
    bitmap = lb_pair.bin_array_bitmap
    while True:
        if start < lower_default or start > upper_default:
            if extension is None:
                return None
            if start < 0:
                if swap_for_y:
                    found = _find_set_bit(start, ext_min, extension)
                    if found is not None:
                        return found
                    return None
                found = _find_set_bit(start, -BIN_ARRAY_BITMAP_SIZE - 1, extension)
                if found is not None:
                    return found
                start = lower_default
            else:
                if swap_for_y:
                    found = _find_set_bit(start, BIN_ARRAY_BITMAP_SIZE, extension)
                    if found is not None:
                        return found
                    start = upper_default
                else:
                    found = _find_set_bit(start, ext_max, extension)
                    if found is not None:
                        return found
                    return None
        else:
            offset = start + BIN_ARRAY_BITMAP_SIZE
            if swap_for_y:
                # Highest set bit at or below `offset` (pinned msb of the
                # shifted U1024 returns its leading-zero count, and the
                # shift drops bits past the register width).
                cropped = (bitmap << (1023 - offset)) & ((1 << 1024) - 1)
                if cropped:
                    return start - (1023 - (cropped.bit_length() - 1))
                start = lower_default - 1
            else:
                cropped = bitmap >> offset
                if cropped:
                    return start + ((cropped & -cropped).bit_length() - 1)
                start = upper_default + 1


def _find_set_bit(
    start_index: int, end_index: int, extension: DlmmBinArrayBitmapExtension
) -> int | None:
    """Pinned findSetBit: scan [start, end] inclusive in either direction."""
    step = 1 if start_index <= end_index else -1
    for i in range(start_index, end_index + step, step):
        if extension_bin_array_initialized(extension, i):
            return i
    return None


# --- Token-2022 transfer-fee / transfer-hook evidence (token_2022.ts) ------


@dataclass(frozen=True, slots=True)
class DlmmTokenMintEvidence:
    """Parsed Token-2022 mint transfer evidence (fail-closed otherwise)."""

    mint: str
    token_program: str
    transfer_fee_epoch: int | None = None
    transfer_fee_basis_points: int | None = None
    transfer_fee_maximum: int | None = None
    has_transfer_hook: bool = False
    unknown_extension_tags: tuple[int, ...] = ()


def decode_dlmm_token_mint_evidence(account: NativeAccount) -> DlmmTokenMintEvidence:
    """Parse a Token-2022 mint's TLV extension region (fail-closed).

    Only the extensions the pinned quote path consumes are interpreted
    (TransferFeeConfig, TransferHook); any other non-zero tag is surfaced as
    ``unknown_extension_tags`` and the quote caller must reject.
    """
    data = account.require(TOKEN_2022_PROGRAM_ID)
    if len(data) < 82 + 2:
        raise NativeCaptureError("Token-2022 mint layout too short")
    tlv_len = int.from_bytes(data[-2:], "little")
    if tlv_len == 0 or len(data) < 82 + tlv_len:
        raise NativeCaptureError("Token-2022 mint TLV length incoherent")
    region = data[82 : 82 + tlv_len]
    fee_epoch = fee_bps = fee_max = None
    has_hook = False
    unknown: list[int] = []
    pos = 0
    while pos + 4 <= len(region):
        tag = int.from_bytes(region[pos : pos + 2], "little")
        length = int.from_bytes(region[pos + 2 : pos + 4], "little")
        payload = region[pos + 4 : pos + 4 + length]
        if tag == 0:
            break
        if tag == TL_TRANSFER_FEE_CONFIG and length >= 18:
            fee_epoch = int.from_bytes(payload[0:8], "little")
            fee_max = int.from_bytes(payload[8:16], "little")
            fee_bps = int.from_bytes(payload[16:18], "little")
        elif tag == TL_TRANSFER_HOOK and length >= 32:
            program = str(Pubkey.from_bytes(payload[0:32]))
            has_hook = program != "11111111111111111111111111111111"
        else:
            unknown.append(tag)
        pos += 4 + length
    return DlmmTokenMintEvidence(
        account.address,
        TOKEN_2022_PROGRAM_ID,
        fee_epoch,
        fee_bps,
        fee_max,
        has_hook,
        tuple(unknown),
    )


def _token_evidence_for(
    mint: str, token_program: str, evidence: DlmmTokenMintEvidence | None
) -> DlmmTokenMintEvidence | None:
    if token_program == SPL_TOKEN_PROGRAM_ID:
        return None
    if evidence is None or evidence.mint != mint:
        raise NativeCaptureError(
            "DLMM_TOKEN_2022_TRANSFER_FEE_UNRESOLVED: Token-2022 mint "
            "requires decoded transfer evidence"
        )
    if evidence.unknown_extension_tags:
        raise NativeCaptureError(
            "DLMM_TOKEN_2022_UNKNOWN_EXTENSION: " f"{evidence.unknown_extension_tags}"
        )
    if evidence.has_transfer_hook:
        raise NativeCaptureError(
            "DLMM_TOKEN_2022_TRANSFER_HOOK_UNRESOLVED: transfer-hook "
            "accounts cannot be resolved offline"
        )
    return evidence


def _epoch_fee(evidence: DlmmTokenMintEvidence, current_epoch: int):
    """Pinned getEpochFee: newest config with epoch <= current epoch."""
    if evidence.transfer_fee_epoch is None:
        return None
    if evidence.transfer_fee_epoch > current_epoch:
        raise NativeCaptureError("DLMM_TOKEN_2022_TRANSFER_FEE_EPOCH_AHEAD_OF_CLOCK")
    return (
        evidence.transfer_fee_epoch,
        evidence.transfer_fee_basis_points,
        evidence.transfer_fee_maximum,
    )


def _calculate_transfer_fee(config, pre_fee_amount: int) -> int:
    """Pinned calculateFee: floor(pre * bps / MAX_FEE_BASIS_POINTS)."""
    _, bps, maximum = config
    if bps == MAX_FEE_BASIS_POINTS:
        return maximum
    return (pre_fee_amount * bps) // MAX_FEE_BASIS_POINTS


def _calculate_pre_fee_amount(config, post_fee_amount: int) -> int:
    """Pinned calculatePreFeeAmount (ceiling inverse with maximum cap)."""
    _, bps, maximum = config
    if post_fee_amount == 0:
        return 0
    if bps == 0:
        return post_fee_amount
    if bps == MAX_FEE_BASIS_POINTS:
        return post_fee_amount + maximum
    denominator = MAX_FEE_BASIS_POINTS - bps
    raw = (post_fee_amount * MAX_FEE_BASIS_POINTS + denominator - 1) // denominator
    if raw - post_fee_amount >= maximum:
        return post_fee_amount + maximum
    return raw


def calculate_transfer_fee_excluded_amount(
    included_amount: int,
    evidence: DlmmTokenMintEvidence | None,
    current_epoch: int,
) -> int:
    if evidence is None:
        return included_amount
    config = _epoch_fee(evidence, current_epoch)
    if config is None:
        return included_amount
    return included_amount - _calculate_transfer_fee(config, included_amount)


def calculate_transfer_fee_included_amount(
    excluded_amount: int,
    evidence: DlmmTokenMintEvidence | None,
    current_epoch: int,
) -> int:
    if evidence is None:
        return excluded_amount
    config = _epoch_fee(evidence, current_epoch)
    if config is None:
        return excluded_amount
    _, bps, _ = config
    if bps == MAX_FEE_BASIS_POINTS:
        # Pinned: transferFee = maximumFee, included = excluded + maximum.
        return excluded_amount + _calculate_transfer_fee(config, excluded_amount)
    return _calculate_pre_fee_amount(config, excluded_amount)


# --- pinned fee helpers (fee.ts) -------------------------------------------


def get_base_fee(lb_pair: LbPairState) -> int:
    return (
        lb_pair.base_factor
        * lb_pair.bin_step
        * 10
        * (10**lb_pair.base_fee_power_factor)
    )


def get_variable_fee(lb_pair: LbPairState, volatility_accumulator: int) -> int:
    if lb_pair.variable_fee_control > 0:
        square_vfa_bin = (volatility_accumulator * lb_pair.bin_step) ** 2
        v_fee = lb_pair.variable_fee_control * square_vfa_bin
        return (v_fee + 99_999_999_999) // 100_000_000_000
    return 0


def get_total_fee(lb_pair: LbPairState, volatility_accumulator: int) -> int:
    total = get_base_fee(lb_pair) + get_variable_fee(lb_pair, volatility_accumulator)
    return MAX_FEE_RATE if total > MAX_FEE_RATE else total


def update_reference(
    active_id: int, lb_pair: LbPairState, current_timestamp: int
) -> tuple[int, int, int]:
    """Pinned DLMM.updateReference; returns (vol_ref, index_ref, vol_acc)."""
    elapsed = current_timestamp - lb_pair.variable_last_update_timestamp
    vol_ref = lb_pair.volatility_reference
    index_ref = lb_pair.index_reference
    vol_acc = lb_pair.volatility_accumulator
    if elapsed >= lb_pair.filter_period:
        index_ref = active_id
        if elapsed < lb_pair.decay_period:
            vol_ref = (vol_acc * lb_pair.reduction_factor) // BASIS_POINT_MAX
        else:
            vol_ref = 0
    return vol_ref, index_ref, vol_acc


def update_volatility_accumulator(
    vol_ref: int, index_ref: int, lb_pair: LbPairState, active_id: int
) -> int:
    delta_id = abs(index_ref - active_id)
    return min(vol_ref + delta_id * BASIS_POINT_MAX, lb_pair.max_volatility_accumulator)


def _fee_mode(lb_pair: LbPairState, swap_for_y: bool) -> bool:
    if lb_pair.collect_fee_mode == 0:  # InputOnly
        return True
    if lb_pair.collect_fee_mode == 1:  # OnlyY
        return not swap_for_y
    raise NativeCaptureError("unsupported DLMM collect fee mode")


def _support_limit_order(lb_pair: LbPairState) -> bool:
    """Pinned isSupportLimitOrder; limit-order pairs are excluded fail-closed."""
    return lb_pair.function_type in (0, 2)


# --- per-bin quote primitives (bin.ts verbatim ports) -----------------------


def _mul_div(x: int, y: int, denominator: int, *, round_up: bool) -> int:
    quotient, remainder = divmod(x * y, denominator)
    if round_up and remainder:
        return quotient + 1
    return quotient


def _get_amount_out(
    bin_amount_in_reserve: int, in_amount: int, price: int, *, swap_for_y: bool
) -> int:
    if swap_for_y:
        return _mul_div(in_amount, price, 1 << SCALE_OFFSET, round_up=False)
    return _mul_div(in_amount, 1 << SCALE_OFFSET, price, round_up=False)


def _get_amount_in(out_amount: int, price: int, *, swap_for_y: bool) -> int:
    if swap_for_y:
        return _mul_div(out_amount, 1 << SCALE_OFFSET, price, round_up=True)
    return _mul_div(out_amount, price, 1 << SCALE_OFFSET, round_up=True)


def _get_excluded_fee_amount(in_amount: int, fee_numerator: int):
    fee = (in_amount * fee_numerator + (FEE_PRECISION - 1)) // FEE_PRECISION
    return in_amount - fee, fee


def _get_included_fee_amount(excluded_amount: int, fee_numerator: int):
    denominator = FEE_PRECISION - fee_numerator
    included = (excluded_amount * FEE_PRECISION + denominator - 1) // denominator
    return included, included - excluded_amount


def _split_fee(trading_fee: int, protocol_share: int, total_amount_in: int):
    """Pinned splitFee with mmAmountIn == totalAmountIn (no limit orders)."""
    if total_amount_in == 0:
        return 0, 0
    mm_fee = (trading_fee * total_amount_in + total_amount_in - 1) // total_amount_in
    total_lo_fee = trading_fee - mm_fee
    lo_fee = (total_lo_fee * LIMIT_ORDER_FEE_SHARE) // BASIS_POINT_MAX
    lo_protocol_fee = total_lo_fee - lo_fee
    mm_protocol_fee = (mm_fee * protocol_share) // BASIS_POINT_MAX
    total_protocol_fee = lo_protocol_fee + mm_protocol_fee
    return trading_fee - total_protocol_fee, total_protocol_fee


def _swap_exact_in_quote_at_bin(
    bin_state: DlmmBin,
    lb_pair: LbPairState,
    volatility_accumulator: int,
    in_amount: int,
    *,
    swap_for_y: bool,
    fee_on_input: bool,
):
    fee_numerator = get_total_fee(lb_pair, volatility_accumulator)
    trading_fee = 0
    excluded_fee_amount_in = in_amount
    if fee_on_input:
        excluded_fee_amount_in, trading_fee = _get_excluded_fee_amount(
            in_amount, fee_numerator
        )
    max_amount_out = bin_state.amount_y if swap_for_y else bin_state.amount_x
    max_amount_in = _get_amount_in(
        max_amount_out, bin_state.price, swap_for_y=swap_for_y
    )
    if excluded_fee_amount_in >= max_amount_in:
        amount_in = max_amount_in
        amount_left = excluded_fee_amount_in - max_amount_in
        out_amount = max_amount_out
        mm_amount_in = max_amount_in
    else:
        amount_in = excluded_fee_amount_in
        amount_left = 0
        out_amount = _get_amount_out(
            max_amount_out,
            excluded_fee_amount_in,
            bin_state.price,
            swap_for_y=swap_for_y,
        )
        mm_amount_in = excluded_fee_amount_in
    included_fee_amount_in = in_amount
    if amount_left != 0:
        excluded_fee_amount_in -= amount_left
        if fee_on_input:
            included_fee_amount_in, trading_fee = _get_included_fee_amount(
                excluded_fee_amount_in, fee_numerator
            )
        else:
            included_fee_amount_in = excluded_fee_amount_in
    excluded_fee_amount_out = out_amount
    if not fee_on_input:
        trading_fee = (
            out_amount * fee_numerator + (FEE_PRECISION - 1)
        ) // FEE_PRECISION
        excluded_fee_amount_out = out_amount - trading_fee
    fee, protocol_fee = _split_fee(trading_fee, lb_pair.protocol_share, mm_amount_in)
    return included_fee_amount_in, excluded_fee_amount_out, fee, protocol_fee


@dataclass(frozen=True, slots=True)
class DlmmSwapQuote:
    consumed_in_amount: int
    out_amount: int
    fee: int
    protocol_fee: int
    min_out_amount: int
    end_price_numerator: int
    end_price_denominator: int
    end_bin_id: int
    active_bin_id_start: int
    bins_used: tuple[int, ...]
    bin_arrays_used: tuple[str, ...]
    fee_on_input: bool
    partial_fill: bool
    transfer_fee_in: int
    transfer_fee_out: int
    decoder_revision: str = DLMM_DECODER_REVISION
    quote_revision: str = DLMM_QUOTE_REVISION
    evidence_state: str = "VENUE_STATE_DECODED"

    @property
    def consumed_input_matches_request(self) -> bool:
        return not self.partial_fill


def dlmm_swap_exact_in_quote(
    lb_pair: LbPairState,
    bin_arrays: tuple[DlmmBinArray, ...],
    amount_in: int,
    *,
    swap_for_y: bool,
    allowed_slippage_bps: int = 0,
    clock_epoch: int,
    current_timestamp: int,
    is_partial_fill: bool = False,
    bin_array_bitmap_extension: DlmmBinArrayBitmapExtension | None = None,
    in_mint_evidence: DlmmTokenMintEvidence | None = None,
    out_mint_evidence: DlmmTokenMintEvidence | None = None,
    max_bins: int = 60_000,
) -> DlmmSwapQuote:
    """Pinned DLMM.swapQuote (exact-in, integer port of the SDK closure).

    Requires a coherent LbPair + the complete reachable BinArray set (and the
    bitmap extension when the walk leaves the default 512-array window).
    ``current_timestamp`` (Unix seconds) drives the pinned volatility
    reference decay; ``clock_epoch`` selects Token-2022 transfer-fee epochs.
    Limit-order pairs are rejected fail-closed; a partial-fill quote is only
    returned when ``is_partial_fill`` is set and stays non-promotable.
    """
    if type(amount_in) is not int or not 1 <= amount_in <= U64_MAX:
        raise NativeCaptureError("DLMM exact-in amount out of u64 range")
    if type(clock_epoch) is not int or clock_epoch < 0:
        raise NativeCaptureError("DLMM clock epoch must be a non-negative integer")
    if type(current_timestamp) is not int or current_timestamp < 0:
        raise NativeCaptureError(
            "DLMM current timestamp must be a non-negative integer"
        )
    if not 0 <= allowed_slippage_bps <= BASIS_POINT_MAX:
        raise NativeCaptureError("DLMM allowed slippage out of bps range")
    if not isinstance(max_bins, int) or not 1 <= max_bins <= 60_000:
        raise NativeCaptureError("bounded quote-bin window required")
    if not lb_pair.enabled:
        raise NativeCaptureError("DLMM pair disabled by status byte")
    if not lb_pair.min_bin_id <= lb_pair.active_id <= lb_pair.max_bin_id:
        raise NativeCaptureError("DLMM active id outside pinned pair bin range")
    if _support_limit_order(lb_pair):
        raise NativeCaptureError(
            "DLMM_LIMIT_ORDER_PAIR_REJECTED: limit-order participation "
            "cannot be modeled offline"
        )
    fee_on_input = _fee_mode(lb_pair, swap_for_y)
    in_program = lb_pair.token_x_program if swap_for_y else lb_pair.token_y_program
    out_program = lb_pair.token_y_program if swap_for_y else lb_pair.token_x_program
    in_mint = lb_pair.token_x_mint if swap_for_y else lb_pair.token_y_mint
    out_mint = lb_pair.token_y_mint if swap_for_y else lb_pair.token_x_mint
    in_evidence = _token_evidence_for(in_mint, in_program, in_mint_evidence)
    out_evidence = _token_evidence_for(out_mint, out_program, out_mint_evidence)

    transfer_fee_excluded_in = calculate_transfer_fee_excluded_amount(
        amount_in, in_evidence, clock_epoch
    )
    vol_ref, index_ref, vol_acc = update_reference(
        lb_pair.active_id, lb_pair, current_timestamp
    )
    in_amount_left = transfer_fee_excluded_in
    active_id = lb_pair.active_id
    arrays: dict[int, DlmmBinArray] = {}
    for array in bin_arrays:
        if array.lb_pair != lb_pair.address:
            raise NativeCaptureError("bin array pair binding mismatch")
        if array.version != 0:
            raise NativeCaptureError("unsupported DLMM BinArray version byte")
        if array.index not in arrays:
            arrays[array.index] = array
    if not arrays:
        raise NativeCaptureError("DLMM reachable bin array set empty")
    if bin_array_index_for_bin_id(lb_pair.active_id) not in arrays:
        raise NativeCaptureError("DLMM active bin array missing")

    total_out = 0
    fee_amount = 0
    protocol_fee_amount = 0
    bins_used: list[int] = []
    arrays_used: list[str] = []
    last_filled_active_id: int | None = None
    partial = False
    steps = 0
    while in_amount_left > 0:
        steps += 1
        if steps > max_bins:
            raise NativeCaptureError("DLMM_TRAVERSAL_LIMIT_EXCEEDED")
        index = find_next_bin_array_index_with_liquidity(
            swap_for_y, active_id, lb_pair, bin_array_bitmap_extension
        )
        if index is None or index not in arrays:
            if is_partial_fill:
                partial = True
                break
            raise NativeCaptureError(
                "DLMM_SWAP_QUOTE_INSUFFICIENT_LIQUIDITY: reachable bin "
                "array set exhausted before input consumed"
            )
        array = arrays[index]
        if array.address not in arrays_used:
            arrays_used.append(array.address)
        lower = index * BINS_PER_BIN_ARRAY
        upper = lower + BINS_PER_BIN_ARRAY - 1
        if lower <= active_id <= upper:
            bin_state = array.bin(active_id)
            max_out = bin_state.amount_y if swap_for_y else bin_state.amount_x
            if max_out != 0:
                vol_acc = update_volatility_accumulator(
                    vol_ref, index_ref, lb_pair, active_id
                )
                amount_in_bin, amount_out_bin, fee_bin, protocol_bin = (
                    _swap_exact_in_quote_at_bin(
                        bin_state,
                        lb_pair,
                        vol_acc,
                        in_amount_left,
                        swap_for_y=swap_for_y,
                        fee_on_input=fee_on_input,
                    )
                )
                if amount_in_bin != 0:
                    in_amount_left -= amount_in_bin
                    total_out += amount_out_bin
                    fee_amount += fee_bin
                    protocol_fee_amount += protocol_bin
                    bins_used.append(active_id)
                    last_filled_active_id = active_id
        if in_amount_left > 0:
            active_id = active_id - 1 if swap_for_y else active_id + 1
        if not lb_pair.min_bin_id <= active_id <= lb_pair.max_bin_id:
            if is_partial_fill:
                partial = True
                break
            raise NativeCaptureError(
                "DLMM_SWAP_QUOTE_INSUFFICIENT_LIQUIDITY: walk left the "
                "pinned pair bin-id range before input consumed"
            )
    if last_filled_active_id is None:
        raise NativeCaptureError("DLMM_INSUFFICIENT_ACTIVE_LIQUIDITY")
    if in_amount_left > 0 and not partial:
        raise NativeCaptureError("DLMM_TRAVERSAL_INCONSISTENT")
    consumed_excluded = transfer_fee_excluded_in - in_amount_left
    consumed_included = calculate_transfer_fee_included_amount(
        consumed_excluded, in_evidence, clock_epoch
    )
    if consumed_included > amount_in:
        consumed_included = amount_in
    out_after_transfer = calculate_transfer_fee_excluded_amount(
        total_out, out_evidence, clock_epoch
    )
    min_out = (out_after_transfer * (BASIS_POINT_MAX - allowed_slippage_bps)) // (
        BASIS_POINT_MAX
    )
    transfer_fee_in = consumed_included - consumed_excluded
    transfer_fee_out = total_out - out_after_transfer
    # Pinned endPrice is the Decimal (1 + binStep/10^4)^binId display value;
    # the exact rational is reported as an integer numerator/denominator pair.
    bin_step = lb_pair.bin_step
    n = 10_000 + bin_step
    d = 10_000
    end_num = (
        n**last_filled_active_id
        if last_filled_active_id >= 0
        else d ** (-last_filled_active_id)
    )
    end_den = (
        d**last_filled_active_id
        if last_filled_active_id >= 0
        else n ** (-last_filled_active_id)
    )
    return DlmmSwapQuote(
        consumed_included,
        out_after_transfer,
        fee_amount,
        protocol_fee_amount,
        min_out,
        end_num,
        end_den,
        last_filled_active_id,
        lb_pair.active_id,
        tuple(bins_used),
        tuple(arrays_used),
        fee_on_input,
        partial,
        transfer_fee_in,
        transfer_fee_out,
    )
