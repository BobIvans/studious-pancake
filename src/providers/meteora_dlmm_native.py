"""Strict Meteora DLMM LbPair/BinArray decoding and reachable-state walk.

Layouts and discriminators are pinned to the checked-in Anchor IDL snapshot
``docs/integrations/offline/solana-p0/vendor-reference/meteora/lb_clmm.idl.json``
(metadata 0.12.0, program ``LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo``,
blob-verified). Account byte sizes (LbPair 904, BinArray 10136) follow from
the IDL's fixed-width fields including its explicit padding tombstones.

Honest capability boundary: the exact per-bin amount-specific quote math is
NOT implementable from the pinned snapshots — the SDK's ``./constants`` and
``./helpers`` modules (``BASIS_POINT_MAX``, ``SCALE_OFFSET``, the
``swapExactInQuoteAtBin``/``getBinMaxAmountOut``/``getPriceOfBinByBinId``
bodies) are not vendored. Amount-specific DLMM quotes therefore fail closed
with ``DLMM_AMOUNT_SPECIFIC_QUOTE_MISSING_PIN``; what this module provides is
exact account state (owner/discriminator/version, mints, token-program flags,
reserves, active bin, fee parameters) and the reachable-bin walk used for
state verification. Indexed liquidity never becomes executable depth here.
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

LB_PAIR_LEN = 904
BIN_ARRAY_LEN = 10136
BINS_PER_BIN_ARRAY = 70
BIN_LEN = 144
SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

PAIR_STATUS_ENABLED = 0
PAIR_TYPE_NAMES = {
    0: "Permissionless",
    1: "Permission",
    2: "CustomizablePermissionless",
    3: "PermissionlessV2",
}


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

    @property
    def enabled(self) -> bool:
        return self.status == PAIR_STATUS_ENABLED

    @property
    def pair_type_name(self) -> str:
        return PAIR_TYPE_NAMES.get(self.pair_type, "UNKNOWN")


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
    amount_specific_quote: str = "DLMM_AMOUNT_SPECIFIC_QUOTE_MISSING_PIN"
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
    """Always fails closed: the per-bin quote bodies are not pinned offline."""
    raise NativeCaptureError(
        "DLMM_AMOUNT_SPECIFIC_QUOTE_MISSING_PIN: swapExactInQuoteAtBin/"
        "getBinMaxAmountOut/getPriceOfBinByBinId and the SDK constants "
        "(BASIS_POINT_MAX, SCALE_OFFSET) are not vendored; capture the "
        "official SDK artifacts before any amount-specific DLMM quote"
    )
