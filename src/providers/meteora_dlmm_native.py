"""Strict Meteora DLMM direct-state decoding and exact-in bin-walk math.

Canonical owner for Meteora DLMM LbPair, BinArray, BinArrayBitmapExtension and
the amount-specific ExactIn quote. Account layouts are transcribed from the
pinned offline Anchor IDL snapshot
``docs/integrations/offline/solana-p0/vendor-reference/meteora/lb_clmm.idl.json``
(MeteoraAg/dlmm-sdk @ 1532e540db41ac405dbf4c5bb2ddfceaa1f98ff1, IDL metadata
version 0.12.0, program ``LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo``,
package license ISC per pinned package.json). Helper/quote-loop logic is
transcribed from the mirrored ``dlmm_index.ts.txt``, ``lbPair.ts.txt`` and
``binArray.ts.txt`` snapshots.

Direction semantics (all pinned fragments agree):
- the mirrored swapQuote loop advances ``activeId = activeId - 1`` when
  ``swapForY`` is true and ``+1`` otherwise;
- ``getFeeMode`` (lbPair.ts) returns ``feeOnTokenX = swapForY`` for
  ``CollectFeeMode.InputOnly`` where the fee is on the input token, hence
  ``swapForY = true`` means token X is the input and token Y the output;
- therefore the stored bin price is the amount of token Y per token X, rising
  with the bin id; an X->Y swap walks down into Y-rich lower bins and a Y->X
  swap walks up into X-rich upper bins.

Price scale: the mirrored ``syncWithMarketPrice`` converts a stored
``bin.price`` into a human price by dividing by ``2**64 - 1``, so the stored
u128 price is the Y-per-X fraction scaled by ``2**64`` (Q64); this is the only
offline-pinned scale fragment and is tagged in the math provenance.

Provenance tags:
- ``[PINNED]``: transcribed from a mirrored upstream file/IDL.
- ``[DOCUMENTED]``: arithmetic documented for the same program family but not
  present in the mirrored file set (per-bin swap amounts/rounding, the variable
  fee formula, ``FEE_PRECISION``/``BASIS_POINT_MAX`` numeric constants, and the
  fee split). The quote result exposes ``math_provenance`` and supports
  ``variable_fee_policy="fail_closed"`` so dynamic-fee pools are never quoted
  from an unpinned formula unless explicitly enabled.

Fail-closed policy: unknown layout/discriminator, wrong program owner, disabled
or unknown pair status, unsupported pair/function types, limit-order state,
Token-2022 flags, pre-activation pairs, missing bin arrays, missing bitmap
extension outside the default bitmap range, reserve/bin coherence violations
and stale/incoherent slots all raise :class:`DlmmCaptureError`. Unknown is
never zero; no quote is returned from incomplete bin data. No signer, no
sender, no network.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
from typing import Any, Literal, Mapping

from solders.pubkey import Pubkey

from src.providers.raydium_cpmm_native import NativeAccount, NativeCaptureError
from src.providers.raydium_cpmm_native import content_hash
from src.strategy.exact_cpmm_capacity import MAINNET_GENESIS, SPL_TOKEN_PROGRAM

SCHEMA = "shadow.meteora-dlmm-native-capture.v1"
DECODER_REVISION = "p0-3.meteora-dlmm-native.v1"
SOURCE_REVISION = "dlmm-sdk@1532e540db41ac405dbf4c5bb2ddfceaa1f98ff1"

# [PINNED] lb_clmm.idl.json metadata address; SOURCE_MANIFEST.json program_id_mainnet
METEORA_DLMM_PROGRAM_ID = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
PROGRAM = Pubkey.from_string(METEORA_DLMM_PROGRAM_ID)
LOADER = "BPFLoaderUpgradeab1e11111111111111111111111"
CLOCK = "SysvarC1ock11111111111111111111111111111111"
SYSVAR_OWNER = "Sysvar1111111111111111111111111111111111111"

# [PINNED] IDL struct sizes (bytemuck, repr(C)); totals include the 8-byte
# Anchor discriminator.
LB_PAIR_LEN = 904  # 8 + 896
BIN_ARRAY_LEN = 10136  # 8 + 10128 (70 bins x 144)
BIN_ARRAY_BITMAP_EXTENSION_LEN = 1576  # 8 + 1568
ORACLE_MIN_LEN = 32  # 8 + idx/active_size/length; account may be reallocated

# [PINNED] binArray.ts constants (BIN_ARRAY_BITMAP_SIZE=512, MAX_BIN_ARRAY_SIZE=70,
# EXTENSION_BINARRAY_BITMAP_SIZE=12 as used by the mirrored helpers).
BIN_ARRAY_BITMAP_SIZE = 512
MAX_BIN_ARRAY_SIZE = 70
EXTENSION_BINARRAY_BITMAP_SIZE = 12
INTERNAL_BITMAP_MIN = -BIN_ARRAY_BITMAP_SIZE
INTERNAL_BITMAP_MAX = BIN_ARRAY_BITMAP_SIZE - 1
EXTENSION_RANGE_MIN = -BIN_ARRAY_BITMAP_SIZE * (EXTENSION_BINARRAY_BITMAP_SIZE + 1)
EXTENSION_RANGE_MAX = BIN_ARRAY_BITMAP_SIZE * (EXTENSION_BINARRAY_BITMAP_SIZE + 1) - 1

# [DOCUMENTED] SDK numeric constants (names pinned by dlmm_index.ts imports;
# values from the public dlmm-sdk constants module, cross-checked against the
# pinned formulas that use them: updateReference divides reduction_factor by
# BASIS_POINT_MAX, calculateFeeInfo divides by FEE_PRECISION, protocol share
# is divided by BASIS_POINT_MAX per the IDL doc comment).
FEE_PRECISION = 1_000_000_000
BASIS_POINT_MAX = 10_000
VARIABLE_FEE_DENOMINATOR = 10**11  # DOCUMENTED fraction (x/1e20) scaled by 1e9

# [PINNED] dlmm_index.ts syncWithMarketPrice divides the stored bin price by
# 2**64 - 1, so the stored u128 price is the Y-per-X fraction scaled by 2**64.
PRICE_SHIFT = 64

# [PINNED] IDL enums (values follow Rust discriminant order in the IDL/SDK):
# PairStatus 0=Enabled 1=Disabled; PairType 0..3; ActivationType 0=Slot 1=Timestamp
PAIR_STATUS_ENABLED = 0
PAIR_TYPE_VALUES = (0, 1, 2, 3)
ACTIVATION_TYPE_SLOT = 0
ACTIVATION_TYPE_TIMESTAMP = 1
# CollectFeeMode: 0=InputOnly, 1=OnlyY [PINNED lbPair.ts getFeeMode + IDL]
COLLECT_FEE_MODE_INPUT_ONLY = 0
COLLECT_FEE_MODE_ONLY_Y = 1
# FunctionType: 0=Undetermined, 1=LiquidityMining, 2=LimitOrder [DOCUMENTED
# discriminants; LimitOrder pools are rejected because getBinMaxAmountOut's
# limit-order branch is not mirrored]
FUNCTION_TYPE_UNDETERMINED = 0
FUNCTION_TYPE_LIQUIDITY_MINING = 1
FUNCTION_TYPE_LIMIT_ORDER = 2
FUNCTION_TYPE_VALUES = (
    FUNCTION_TYPE_UNDETERMINED,
    FUNCTION_TYPE_LIQUIDITY_MINING,
)
# TokenProgramFlags: 0=SPL Token, 1=Token-2022 [PINNED lbPair.ts getTokenProgramId]
TOKEN_PROGRAM_FLAG_SPL = 0

_U1024_MASK = (1 << 1024) - 1
MAX_BINS_WALKED = 600  # bounded computation guard (documented, not upstream)

MATH_PROVENANCE = (
    "PINNED:vendor-reference/meteora/{lb_clmm.idl.json,dlmm_index.ts,lbPair.ts,"
    "binArray.ts}@1532e540db41ac405dbf4c5bb2ddfceaa1f98ff1 (IDL 0.12.0)",
    "DOCUMENTED:per-bin swap amount/rounding, variable-fee formula, fee split, "
    "FEE_PRECISION/BASIS_POINT_MAX values (dlmm-sdk math module not mirrored)",
)


class DlmmCaptureError(ValueError):
    """Missing, malformed or incoherent DLMM evidence; never a zero quote."""


def _owned_data(account: NativeAccount, owner: str, length: int | None = None) -> bytes:
    """Fail-closed ownership/length check, re-raised as a venue error."""
    try:
        return account.require(owner, length)
    except NativeCaptureError as exc:
        raise DlmmCaptureError(str(exc)) from exc


def _account_from_rpc(address: Any, value: Any) -> NativeAccount:
    try:
        return NativeAccount.from_rpc(address, value)
    except NativeCaptureError as exc:
        raise DlmmCaptureError(str(exc)) from exc


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
        raise DlmmCaptureError(f"unsupported {name} layout/discriminator")


def _div_ceil(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


# ---------------------------------------------------------------------------
# Pinned bin-array index helpers (binArray.ts)
# ---------------------------------------------------------------------------


def bin_id_to_bin_array_index(bin_id: int) -> int:
    """[PINNED binArray.ts binIdToBinArrayIndex] BN.js truncated divmod by 70."""
    if bin_id >= 0:
        return bin_id // MAX_BIN_ARRAY_SIZE
    quotient = -((-bin_id) // MAX_BIN_ARRAY_SIZE)  # truncation toward zero
    remainder = bin_id - quotient * MAX_BIN_ARRAY_SIZE  # carries the sign
    if remainder != 0:
        quotient -= 1
    return quotient


def bin_array_lower_upper_bin_id(bin_array_index: int) -> tuple[int, int]:
    """[PINNED binArray.ts getBinArrayLowerUpperBinId]"""
    lower = bin_array_index * MAX_BIN_ARRAY_SIZE
    return lower, lower + MAX_BIN_ARRAY_SIZE - 1


def is_bin_id_within_bin_array(bin_id: int, bin_array_index: int) -> bool:
    """[PINNED binArray.ts isBinIdWithinBinArray]"""
    lower, upper = bin_array_lower_upper_bin_id(bin_array_index)
    return lower <= bin_id <= upper


def bin_offset_in_bin_array(bin_id: int, bin_array_index: int) -> int:
    """[PINNED binArray.ts getBinFromBinArray] negative arrays store reversed."""
    lower, upper = bin_array_lower_upper_bin_id(bin_array_index)
    if bin_id > 0:
        return bin_id - lower
    return MAX_BIN_ARRAY_SIZE - (upper - bin_id) - 1


def is_overflow_default_bin_array_bitmap(bin_array_index: int) -> bool:
    """[PINNED binArray.ts isOverflowDefaultBinArrayBitmap]"""
    return (
        bin_array_index > INTERNAL_BITMAP_MAX or bin_array_index < INTERNAL_BITMAP_MIN
    )


def _build_bitmap(u64_words: tuple[int, ...], bits: int) -> int:
    """[PINNED binArray.ts buildBitmapFromU64Arrays] little-endian concat."""
    value = 0
    for shift, word in enumerate(u64_words):
        value |= word << (64 * shift)
    return value & ((1 << bits) - 1)


def _most_significant_bit(number: int, bit_length: int) -> int | None:
    """[PINNED binArray.ts mostSignificantBit] leading zeros within bit_length."""
    if number == 0:
        return None
    return bit_length - number.bit_length()


def _least_significant_bit(number: int, bit_length: int) -> int | None:
    """[PINNED binArray.ts leastSignificantBit]"""
    if number == 0:
        return None
    return (number & -number).bit_length() - 1


def _extension_bin_array_offset(bin_array_index: int) -> int:
    """[PINNED binArray.ts findSetBit getBinArrayOffset]"""
    if bin_array_index > 0:
        return bin_array_index % BIN_ARRAY_BITMAP_SIZE
    return (-(bin_array_index + 1)) % BIN_ARRAY_BITMAP_SIZE


def _extension_bitmap_offset(bin_array_index: int) -> int:
    """[PINNED binArray.ts findSetBit getBitmapOffset]"""
    if bin_array_index > 0:
        return bin_array_index // BIN_ARRAY_BITMAP_SIZE - 1
    return (-(bin_array_index + 1)) // BIN_ARRAY_BITMAP_SIZE - 1


def _find_set_bit(start: int, end: int, extension: "DlmmBitmapExtension") -> int | None:
    """[PINNED binArray.ts findSetBit] scan start..end (either direction)."""
    if start <= end:
        indices = range(start, end + 1)
    else:
        indices = range(start, end - 1, -1)
    for i in indices:
        offset = _extension_bin_array_offset(i)
        bitmap_offset = _extension_bitmap_offset(i)
        if i > 0:
            if bitmap_offset >= EXTENSION_BINARRAY_BITMAP_SIZE:
                continue
            words = extension.positive_bitmap[bitmap_offset]
        else:
            if bitmap_offset >= EXTENSION_BINARRAY_BITMAP_SIZE:
                continue
            words = extension.negative_bitmap[bitmap_offset]
        bitmap = _build_bitmap(words, 512)
        if (bitmap >> offset) & 1:
            return i
    return None


def find_next_bin_array_index_with_liquidity(
    swap_for_y: bool,
    active_bin_id: int,
    bin_array_bitmap: int,
    extension: "DlmmBitmapExtension | None",
) -> int | None:
    """[PINNED binArray.ts findNextBinArrayIndexWithLiquidity]"""
    start = bin_id_to_bin_array_index(active_bin_id)
    while True:
        if is_overflow_default_bin_array_bitmap(start):
            if extension is None:
                return None
            if start < 0:
                if swap_for_y:
                    found = _find_set_bit(start, EXTENSION_RANGE_MIN, extension)
                    if found is not None:
                        return found
                    return None
                found = _find_set_bit(start, -BIN_ARRAY_BITMAP_SIZE - 1, extension)
                if found is not None:
                    return found
                start = -BIN_ARRAY_BITMAP_SIZE
            else:
                if swap_for_y:
                    found = _find_set_bit(start, BIN_ARRAY_BITMAP_SIZE, extension)
                    if found is not None:
                        return found
                    start = BIN_ARRAY_BITMAP_SIZE - 1
                else:
                    found = _find_set_bit(start, EXTENSION_RANGE_MAX, extension)
                    if found is not None:
                        return found
                    return None
        else:
            offset = start + BIN_ARRAY_BITMAP_SIZE
            if swap_for_y:
                cropped = (bin_array_bitmap << (1023 - offset)) & _U1024_MASK
                msb = _most_significant_bit(cropped, 1024)
                if msb is not None:
                    return start - msb
                start = INTERNAL_BITMAP_MIN - 1
            else:
                cropped = bin_array_bitmap >> offset
                lsb = _least_significant_bit(cropped, 1024)
                if lsb is not None:
                    return start + lsb
                start = INTERNAL_BITMAP_MAX + 1


# ---------------------------------------------------------------------------
# Account decoding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DlmmStaticParameters:
    base_factor: int
    filter_period: int
    decay_period: int
    reduction_factor: int
    variable_fee_control: int
    max_volatility_accumulator: int
    min_bin_id: int
    max_bin_id: int
    protocol_share: int
    base_fee_power_factor: int
    function_type: int
    collect_fee_mode: int


@dataclass(frozen=True, slots=True)
class DlmmVariableParameters:
    volatility_accumulator: int
    volatility_reference: int
    index_reference: int
    last_update_timestamp: int


@dataclass(frozen=True, slots=True)
class DlmmLbPair:
    address: str
    parameters: DlmmStaticParameters
    v_parameters: DlmmVariableParameters
    bump_seed: int
    pair_type: int
    active_id: int
    bin_step: int
    status: int
    activation_type: int
    token_x_mint: str
    token_y_mint: str
    reserve_x: str
    reserve_y: str
    protocol_fee_x: int
    protocol_fee_y: int
    oracle: str
    bin_array_bitmap: int
    last_updated_at: int
    pre_activation_swap_address: str
    activation_point: int
    pre_activation_duration: int
    creator: str
    token_mint_x_program_flag: int
    token_mint_y_program_flag: int
    version: int
    data_sha256: str


def decode_lb_pair(account: NativeAccount) -> DlmmLbPair:
    data = _owned_data(account, METEORA_DLMM_PROGRAM_ID)
    _layout(data, LB_PAIR_LEN, "LbPair")
    status = data[82]
    if status != PAIR_STATUS_ENABLED:
        raise DlmmCaptureError("pair is disabled or has unknown status")
    pair_type = data[75]
    if pair_type not in PAIR_TYPE_VALUES:
        raise DlmmCaptureError("unknown pair type")
    function_type = data[35]
    if function_type not in FUNCTION_TYPE_VALUES:
        if function_type == FUNCTION_TYPE_LIMIT_ORDER:
            raise DlmmCaptureError(
                "BLOCKED(LIMIT_ORDER_POOL_NOT_MIRRORED): getBinMaxAmountOut "
                "limit-order branch not mirrored"
            )
        raise DlmmCaptureError("unknown function type")
    bin_step = _u(data, 80, 2)
    if not 1 <= bin_step <= 1000:
        raise DlmmCaptureError("bin step outside supported bounds")
    parameters = DlmmStaticParameters(
        _u(data, 8, 2),
        _u(data, 10, 2),
        _u(data, 12, 2),
        _u(data, 14, 2),
        _u(data, 16, 4),
        _u(data, 20, 4),
        _i(data, 24, 4),
        _i(data, 28, 4),
        _u(data, 32, 2),
        data[34],
        function_type,
        data[36],
    )
    if parameters.collect_fee_mode not in (
        COLLECT_FEE_MODE_INPUT_ONLY,
        COLLECT_FEE_MODE_ONLY_Y,
    ):
        raise DlmmCaptureError("unknown collect fee mode")
    if parameters.reduction_factor > BASIS_POINT_MAX:
        raise DlmmCaptureError("reduction factor exceeds BASIS_POINT_MAX")
    if parameters.protocol_share > BASIS_POINT_MAX:
        raise DlmmCaptureError("protocol share exceeds BASIS_POINT_MAX")
    active_id = _i(data, 76, 4)
    if not parameters.min_bin_id <= active_id <= parameters.max_bin_id:
        raise DlmmCaptureError("active id outside the pair's supported bin range")
    v_parameters = DlmmVariableParameters(
        _u(data, 40, 4),
        _u(data, 44, 4),
        _i(data, 48, 4),
        _i(data, 56, 8),
    )
    if v_parameters.volatility_accumulator > parameters.max_volatility_accumulator:
        raise DlmmCaptureError("volatility accumulator above its cap")
    x_flag = data[880]
    y_flag = data[881]
    for flag in (x_flag, y_flag):
        if flag != TOKEN_PROGRAM_FLAG_SPL:
            raise DlmmCaptureError(
                "BLOCKED(UNSUPPORTED_TOKEN_PROGRAM): only SPL Token pools are "
                "qualified offline (Token-2022 transfer hooks/fees not mirrored)"
            )
    version = data[882]
    if version > 1:
        raise DlmmCaptureError("unknown LbPair/BinArray version")
    return DlmmLbPair(
        account.address,
        parameters,
        v_parameters,
        data[72],
        pair_type,
        active_id,
        bin_step,
        status,
        data[86],
        _pk(data, 88),
        _pk(data, 120),
        _pk(data, 152),
        _pk(data, 184),
        _u(data, 216),
        _u(data, 224),
        _pk(data, 552),
        _u(data, 584, 128),
        _i(data, 712, 8),
        _pk(data, 752),
        _u(data, 816),
        _u(data, 824),
        _pk(data, 848),
        x_flag,
        y_flag,
        version,
        hashlib.sha256(data).hexdigest(),
    )


@dataclass(frozen=True, slots=True)
class DlmmBin:
    bin_id: int
    amount_x: int
    amount_y: int
    price: int  # stored: Y-per-X fraction scaled by 2**64 [PINNED scale]
    liquidity_supply: int


@dataclass(frozen=True, slots=True)
class DlmmBinArray:
    address: str
    index: int
    version: int
    lb_pair: str
    bins: tuple[DlmmBin, ...]
    data_sha256: str


def decode_bin_array(account: NativeAccount, pair: DlmmLbPair) -> DlmmBinArray:
    data = _owned_data(account, METEORA_DLMM_PROGRAM_ID)
    _layout(data, BIN_ARRAY_LEN, "BinArray")
    index = _i(data, 8, 8)
    version = data[16]
    if version > 1:
        raise DlmmCaptureError("unknown BinArray version")
    if _pk(data, 24) != pair.address:
        raise DlmmCaptureError("bin array bound to a different lb pair")
    lower, upper = bin_array_lower_upper_bin_id(index)
    bins: list[DlmmBin] = []
    for slot in range(MAX_BIN_ARRAY_SIZE):
        base = 56 + slot * 144
        # bin_id for this slot (inverse of bin_offset_in_bin_array)
        if index >= 0:
            bin_id = lower + slot
        else:
            bin_id = upper - slot
        # [PINNED IDL Bin layout] limit-order fields must be empty for
        # non-limit-order pools (qualified set rejects limit-order pools).
        if (
            _u(data, base + 48) != 0
            or _u(data, base + 56) != 0
            or _u(data, base + 112) != 0
            or _u(data, base + 120) != 0
            or _u(data, base + 128) != 0
        ):
            raise DlmmCaptureError("BLOCKED(LIMIT_ORDER_STATE_PRESENT)")
        bins.append(
            DlmmBin(
                bin_id,
                _u(data, base),
                _u(data, base + 8),
                _u(data, base + 16, 16),
                _u(data, base + 32, 16),
            )
        )
    return DlmmBinArray(
        account.address,
        index,
        version,
        _pk(data, 24),
        tuple(bins),
        hashlib.sha256(data).hexdigest(),
    )


@dataclass(frozen=True, slots=True)
class DlmmBitmapExtension:
    address: str
    lb_pair: str
    positive_bitmap: tuple[tuple[int, ...], ...]
    negative_bitmap: tuple[tuple[int, ...], ...]
    data_sha256: str


def decode_bitmap_extension(
    account: NativeAccount, pair: DlmmLbPair
) -> DlmmBitmapExtension:
    data = _owned_data(account, METEORA_DLMM_PROGRAM_ID)
    _layout(data, BIN_ARRAY_BITMAP_EXTENSION_LEN, "BinArrayBitmapExtension")
    if _pk(data, 8) != pair.address:
        raise DlmmCaptureError("bitmap extension bound to a different lb pair")
    positive = tuple(
        tuple(_u(data, 40 + chunk * 64 + word * 8) for word in range(8))
        for chunk in range(EXTENSION_BINARRAY_BITMAP_SIZE)
    )
    negative = tuple(
        tuple(_u(data, 808 + chunk * 64 + word * 8) for word in range(8))
        for chunk in range(EXTENSION_BINARRAY_BITMAP_SIZE)
    )
    return DlmmBitmapExtension(
        account.address,
        _pk(data, 8),
        positive,
        negative,
        hashlib.sha256(data).hexdigest(),
    )


# ---------------------------------------------------------------------------
# Coherent capture envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecodedDlmmCapture:
    pair: DlmmLbPair
    bin_arrays: tuple[DlmmBinArray, ...]
    bitmap_extension: DlmmBitmapExtension | None
    oracle_present: bool
    mints: tuple[str, str]
    reserves: tuple[str, str]
    reserve_amounts: tuple[int, int]
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
        raise DlmmCaptureError(f"bounded {name} list required")
    return raw


def decode_dlmm_capture(payload: Mapping[str, Any]) -> DecodedDlmmCapture:
    if (
        payload.get("schema") != SCHEMA
        or payload.get("decoder_revision") != DECODER_REVISION
    ):
        raise DlmmCaptureError("unsupported capture schema/decoder")
    if payload.get("source_revision") != SOURCE_REVISION:
        raise DlmmCaptureError("unsupported source revision")
    if (
        payload.get("genesis_hash") != MAINNET_GENESIS
        or payload.get("commitment") != "finalized"
    ):
        raise DlmmCaptureError("wrong genesis or non-finalized capture")
    if payload.get("evidence_kind") not in {"captured-rpc", "synthetic-fixture"}:
        raise DlmmCaptureError("explicit evidence kind required")
    if payload.get("live_capture_authorized"):
        raise DlmmCaptureError("BLOCKED(LIVE_CAPTURE_NOT_AUTHORIZED)")
    slot = payload.get("slot")
    if type(slot) is not int or not 1 <= slot <= 2**63 - 1:
        raise DlmmCaptureError("invalid context slot")
    observed = payload.get("observed_at_ns")
    available = payload.get("available_at_ns")
    if type(observed) is not int or type(available) is not int or available < observed:
        raise DlmmCaptureError("invalid capture timing")
    block = payload.get("block")
    if not isinstance(block, dict):
        raise DlmmCaptureError("rooted block required")
    parent_slot = block.get("parentSlot")
    if type(parent_slot) is not int or parent_slot >= slot:
        raise DlmmCaptureError("parent slot must precede context slot")
    block_hash = block.get("blockhash")
    parent_hash = block.get("previousBlockhash")
    block_time = block.get("blockTime")

    def canonical_key(value: Any) -> str:
        if not isinstance(value, str):
            raise DlmmCaptureError("public key fields must be text")
        try:
            parsed = Pubkey.from_string(value)
        except ValueError as exc:
            raise DlmmCaptureError("invalid public key") from exc
        if str(parsed) != value:
            raise DlmmCaptureError("noncanonical public key")
        return value

    canonical_key(block_hash)
    canonical_key(parent_hash)
    if block_hash == parent_hash:
        raise DlmmCaptureError("block hash equals parent hash")
    if type(block_time) is not int or block_time <= 0 or block_time * 10**9 > available:
        raise DlmmCaptureError("invalid rooted block clock")

    raw = _require_bounded_list(payload, "accounts")
    pool_ids = payload.get("pool_ids")
    if (
        not isinstance(pool_ids, list)
        or len(pool_ids) != 1
        or not isinstance(pool_ids[0], str)
    ):
        raise DlmmCaptureError("require exactly one DLMM lb pair address")
    pair_id = canonical_key(pool_ids[0])
    metadata = payload.get("account_response_metadata")
    if not isinstance(metadata, dict) or metadata.get("jsonrpc") != "2.0":
        raise DlmmCaptureError("raw account response envelope required")
    response = copy.deepcopy(metadata)
    result = response.get("result")
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("context"), dict)
        or result["context"].get("slot") != slot
        or "value" in result
    ):
        raise DlmmCaptureError("raw account response context mismatch")
    result["value"] = [
        entry.get("value") if isinstance(entry, dict) else None for entry in raw
    ]
    if content_hash(response) != payload.get("account_response_hash"):
        raise DlmmCaptureError("raw account response hash mismatch")

    accounts: dict[str, NativeAccount] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise DlmmCaptureError("invalid raw account entry")
        account = _account_from_rpc(entry.get("address"), entry.get("value"))
        if account.address in accounts:
            raise DlmmCaptureError("duplicate account address")
        accounts[account.address] = account

    def require(address: str) -> NativeAccount:
        try:
            return accounts[address]
        except KeyError as exc:
            raise DlmmCaptureError("incomplete native account set") from exc

    program_account = require(METEORA_DLMM_PROGRAM_ID)
    if program_account.owner != LOADER or not program_account.executable:
        raise DlmmCaptureError("wrong DLMM deployment owner")
    if len(program_account.data) != 36 or _u(program_account.data, 0, 4) != 2:
        raise DlmmCaptureError("unsupported upgradeable program layout")
    program_data_address = _pk(program_account.data, 4)
    programdata = _owned_data(require(program_data_address), LOADER)
    if (
        len(programdata) <= 45
        or _u(programdata, 0, 4) != 3
        or programdata[12] not in (0, 1)
    ):
        raise DlmmCaptureError("unsupported programdata layout")
    deployment_slot = _u(programdata, 4)
    if deployment_slot > slot:
        raise DlmmCaptureError("deployment newer than bank")
    binary_sha256 = hashlib.sha256(programdata[45:]).hexdigest()

    clock = _owned_data(require(CLOCK), SYSVAR_OWNER, 40)
    if _u(clock, 0) != slot:
        raise DlmmCaptureError("clock slot mismatch")
    clock_timestamp = int.from_bytes(clock[32:40], "little", signed=True)
    clock_epoch = _u(clock, 16)
    if abs(clock_timestamp - block_time) > 2:
        raise DlmmCaptureError("clock/block time incoherent")

    pair = decode_lb_pair(require(pair_id))
    # Activation coherence: pre-activation pairs restrict swaps to the
    # pre-activation address; fail-closed for exact quoting.
    current_point = (
        slot
        if pair.activation_type == ACTIVATION_TYPE_SLOT
        else block_time if pair.activation_type == ACTIVATION_TYPE_TIMESTAMP else None
    )
    if current_point is None or pair.activation_point > current_point:
        raise DlmmCaptureError("BLOCKED(PRE_ACTIVATION_PAIR)")

    mints: list[str] = []
    for mint_address in (pair.token_x_mint, pair.token_y_mint):
        mint_data = _owned_data(require(mint_address), SPL_TOKEN_PROGRAM, 82)
        if mint_data[45] != 1:
            raise DlmmCaptureError("uninitialized mint")
        mints.append(mint_address)
    reserve_amounts: list[int] = []
    for reserve_address in (pair.reserve_x, pair.reserve_y):
        reserve = _owned_data(require(reserve_address), SPL_TOKEN_PROGRAM, 165)
        expected_mint = (
            pair.token_x_mint
            if reserve_address == pair.reserve_x
            else pair.token_y_mint
        )
        if _pk(reserve, 0) != expected_mint:
            raise DlmmCaptureError("reserve mint binding mismatch")
        if reserve[108] != 1 or _u(reserve, 72, 4) != 0:
            raise DlmmCaptureError("reserve state/delegate mismatch")
        reserve_amounts.append(_u(reserve, 64))

    bin_array_ids = payload.get("bin_array_ids")
    if (
        not isinstance(bin_array_ids, list)
        or not 1 <= len(bin_array_ids) <= 64
        or any(not isinstance(v, str) for v in bin_array_ids)
    ):
        raise DlmmCaptureError("require 1..64 dependent bin array addresses")
    bin_arrays: list[DlmmBinArray] = []
    for address in bin_array_ids:
        bin_arrays.append(decode_bin_array(require(canonical_key(address)), pair))
    if len({a.index for a in bin_arrays}) != len(bin_arrays):
        raise DlmmCaptureError("duplicate bin array index")

    bitmap_extension: DlmmBitmapExtension | None = None
    extension_id = payload.get("bin_array_bitmap_extension_id")
    oracle_present = False
    if extension_id is not None:
        bitmap_extension = decode_bitmap_extension(
            require(canonical_key(extension_id)), pair
        )
    if pair.oracle != "11111111111111111111111111111111":
        oracle_account = require(pair.oracle)
        if (
            oracle_account.owner != METEORA_DLMM_PROGRAM_ID
            or len(oracle_account.data) < ORACLE_MIN_LEN
        ):
            raise DlmmCaptureError("unsupported oracle account")
        if oracle_account.data[:8] != hashlib.sha256(b"account:Oracle").digest()[:8]:
            raise DlmmCaptureError("unsupported oracle discriminator")
        oracle_present = True

    expected_accounts = {
        METEORA_DLMM_PROGRAM_ID,
        program_data_address,
        CLOCK,
        pair.address,
        pair.token_x_mint,
        pair.token_y_mint,
        pair.reserve_x,
        pair.reserve_y,
    }
    expected_accounts.update(a.address for a in bin_arrays)
    if bitmap_extension is not None:
        expected_accounts.add(bitmap_extension.address)
    if oracle_present:
        expected_accounts.add(pair.oracle)
    if set(accounts) != expected_accounts:
        raise DlmmCaptureError("unexpected accounts outside coherent native set")

    # Reserve coherence: reserves must cover every decoded bin amount plus the
    # uncollected protocol fee (uncollected composition/limit-order dust aside).
    total_x = pair.protocol_fee_x
    total_y = pair.protocol_fee_y
    for bin_array in bin_arrays:
        for bin_ in bin_array.bins:
            total_x += bin_.amount_x
            total_y += bin_.amount_y
    if reserve_amounts[0] < total_x or reserve_amounts[1] < total_y:
        raise DlmmCaptureError("reserve balances below decoded bin amounts")

    return DecodedDlmmCapture(
        pair,
        tuple(sorted(bin_arrays, key=lambda a: a.index)),
        bitmap_extension,
        oracle_present,
        (mints[0], mints[1]),
        (pair.reserve_x, pair.reserve_y),
        (reserve_amounts[0], reserve_amounts[1]),
        slot,
        block_time,
        clock_epoch,
        binary_sha256,
        deployment_slot,
        content_hash(dict(payload)),
        str(payload["evidence_kind"]),
    )


# ---------------------------------------------------------------------------
# Pinned fee parameter update (dlmm_index.ts)
# ---------------------------------------------------------------------------


def update_reference(
    v_parameters: DlmmVariableParameters,
    s_parameters: DlmmStaticParameters,
    active_id: int,
    current_timestamp: int,
) -> DlmmVariableParameters:
    """[PINNED dlmm_index.ts DLMM.updateReference]"""
    elapsed = current_timestamp - v_parameters.last_update_timestamp
    if elapsed < s_parameters.filter_period:
        return v_parameters
    index_reference = active_id
    if elapsed < s_parameters.decay_period:
        volatility_reference = (
            v_parameters.volatility_accumulator * s_parameters.reduction_factor
        ) // BASIS_POINT_MAX
    else:
        volatility_reference = 0
    return DlmmVariableParameters(
        v_parameters.volatility_accumulator,
        volatility_reference,
        index_reference,
        v_parameters.last_update_timestamp,
    )


def update_volatility_accumulator(
    v_parameters: DlmmVariableParameters,
    s_parameters: DlmmStaticParameters,
    active_id: int,
) -> DlmmVariableParameters:
    """[PINNED dlmm_index.ts DLMM.updateVolatilityAccumulator]"""
    delta_id = abs(v_parameters.index_reference - active_id)
    new_accumulator = v_parameters.volatility_reference + delta_id * BASIS_POINT_MAX
    return DlmmVariableParameters(
        min(new_accumulator, s_parameters.max_volatility_accumulator),
        v_parameters.volatility_reference,
        v_parameters.index_reference,
        v_parameters.last_update_timestamp,
    )


def base_fee_rate(s_parameters: DlmmStaticParameters, bin_step: int) -> int:
    """[PINNED dlmm_index.ts calculateFeeInfo / IDL base_factor doc comment]"""
    return (
        s_parameters.base_factor
        * bin_step
        * 10
        * (10**s_parameters.base_fee_power_factor)
    )


def variable_fee_rate(
    s_parameters: DlmmStaticParameters, volatility_accumulator: int, bin_step: int
) -> int:
    """[DOCUMENTED program fee_math] (bs*va)^2 * control / 1e11, in 1e9 units.

    The documented fraction is (bin_step x va)^2 x variable_fee_control / 1e20;
    scaled into FEE_PRECISION (1e9) units this is division by 1e11. Marked
    DOCUMENTED because dlmm-sdk's math module is not mirrored; callers must
    opt in via variable_fee_policy="documented".
    """
    square = bin_step * volatility_accumulator
    return (square * square * s_parameters.variable_fee_control) // (
        VARIABLE_FEE_DENOMINATOR
    )


# ---------------------------------------------------------------------------
# Exact-in bin walk
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DlmmExactInQuote:
    amount_in: int
    input_left: int
    amount_out: int
    fee: int
    protocol_fee: int
    lp_fee: int
    swap_for_y: bool
    start_bin_id: int
    end_bin_id: int
    bins_used: tuple[int, ...]
    bin_arrays_used: tuple[str, ...]
    fee_on_input: bool
    variable_fee_applied: bool
    math_provenance: tuple[str, ...]


def fee_mode(pair: DlmmLbPair, swap_for_y: bool) -> tuple[bool, bool]:
    """Return (fee_on_input, fee_on_token_x). [PINNED lbPair.ts getFeeMode]"""
    mode = pair.parameters.collect_fee_mode
    if mode == COLLECT_FEE_MODE_INPUT_ONLY:
        return True, swap_for_y
    if mode == COLLECT_FEE_MODE_ONLY_Y:
        return not swap_for_y, False
    raise DlmmCaptureError("unknown collect fee mode")


def _gross_for_net(net: int, fee_rate: int) -> int:
    """Minimal gross g with g - ceil(g*rate/FEE_PRECISION) >= net. [DOCUMENTED]"""
    gross = _div_ceil(net * FEE_PRECISION, FEE_PRECISION - fee_rate)
    while gross - _div_ceil(gross * fee_rate, FEE_PRECISION) < net:
        gross += 1
    while (
        gross > 0
        and (gross - 1) - _div_ceil((gross - 1) * fee_rate, FEE_PRECISION) >= net
    ):
        gross -= 1
    return gross


def _bin_step(
    amount_in_gross: int,
    out_capacity: int,
    price: int,
    *,
    token_x_in: bool,
    fee_rate: int,
    fee_on_input: bool,
    protocol_share: int,
) -> tuple[int, int, int, int]:
    """One bin's exact-in step. [DOCUMENTED per-bin math]

    Returns (consumed_gross, amount_out, fee, protocol_fee).
    price is the stored bin price = amount of token Y per token X scaled by
    2**64 [PINNED scale fragment]:
    - token X in: y_out = floor(net_x * price / 2**64); draining the bin's Y
      needs net_x >= ceil(y_capacity * 2**64 / price).
    - token Y in: x_out = floor(net_y * 2**64 / price); draining the bin's X
      needs net_y >= ceil(x_capacity * price / 2**64).
    Output rounding is floor; fee rounding is ceil (documented). With
    CollectFeeMode.OnlyY the fee is taken from the Y output (fee_on_input is
    false only when X is the input); otherwise it is taken from the input.
    """
    if price <= 0:
        raise DlmmCaptureError("bin price must be positive")
    if token_x_in:
        if fee_on_input:
            drain_net = _div_ceil(out_capacity << PRICE_SHIFT, price)
            net_available = amount_in_gross - _div_ceil(
                amount_in_gross * fee_rate, FEE_PRECISION
            )
            if net_available >= drain_net:
                gross_used = _gross_for_net(drain_net, fee_rate)
                fee = gross_used - drain_net
                out = out_capacity
            else:
                gross_used = amount_in_gross
                fee = _div_ceil(gross_used * fee_rate, FEE_PRECISION)
                net_used = gross_used - fee
                out = (net_used * price) >> PRICE_SHIFT
        else:
            gross_out_full = (amount_in_gross * price) >> PRICE_SHIFT
            if gross_out_full >= out_capacity:
                gross_out = out_capacity
                gross_used = _div_ceil(out_capacity << PRICE_SHIFT, price)
            else:
                gross_out = gross_out_full
                gross_used = amount_in_gross
            fee = _div_ceil(gross_out * fee_rate, FEE_PRECISION)
            out = gross_out - fee
    else:
        # token Y in: the fee is always on the input side for both collect
        # modes (OnlyY charges the Y input; InputOnly charges the input).
        drain_net = _div_ceil(out_capacity * price, 1 << PRICE_SHIFT)
        net_available = amount_in_gross - _div_ceil(
            amount_in_gross * fee_rate, FEE_PRECISION
        )
        if net_available >= drain_net:
            gross_used = _gross_for_net(drain_net, fee_rate)
            fee = gross_used - drain_net
            out = out_capacity
        else:
            gross_used = amount_in_gross
            fee = _div_ceil(gross_used * fee_rate, FEE_PRECISION)
            net_used = gross_used - fee
            out = (net_used << PRICE_SHIFT) // price
    protocol = (fee * protocol_share) // BASIS_POINT_MAX
    return gross_used, out, fee, protocol


def dlmm_exact_in_quote(
    capture: DecodedDlmmCapture,
    amount_in: int,
    *,
    swap_for_y: bool,
    variable_fee_policy: Literal["fail_closed", "documented"] = "fail_closed",
) -> DlmmExactInQuote:
    """Exact-in quote walking reachable bins from coherent captured state."""
    pair = capture.pair
    if type(amount_in) is not int or not 1 <= amount_in <= (1 << 64) - 1:
        raise DlmmCaptureError("amount_in must be a positive u64")
    if capture.bitmap_extension is None:
        overflow_active = is_overflow_default_bin_array_bitmap(
            bin_id_to_bin_array_index(pair.active_id)
        )
        if overflow_active:
            raise DlmmCaptureError(
                "BLOCKED(MISSING_BIN_ARRAY_BITMAP_EXTENSION): active bin array "
                "is outside the default bitmap range"
            )
    arrays_by_index = {a.index: a for a in capture.bin_arrays}
    extension = capture.bitmap_extension
    s_parameters = pair.parameters
    v_parameters = pair.v_parameters
    # [PINNED dlmm_index.ts swapQuote] updateReference runs once on a clone of
    # vParameters using the coherent capture timestamp before the walk.
    v_parameters = update_reference(
        v_parameters, s_parameters, pair.active_id, capture.block_time
    )
    fee_on_input, fee_on_token_x = fee_mode(pair, swap_for_y)
    base_rate = base_fee_rate(s_parameters, pair.bin_step)
    if base_rate >= FEE_PRECISION:
        raise DlmmCaptureError("base fee rate at or above FEE_PRECISION")
    variable_applied = False
    if s_parameters.variable_fee_control != 0:
        if variable_fee_policy != "documented":
            raise DlmmCaptureError(
                "BLOCKED(VARIABLE_FEE_FORMULA_NOT_PINNED): dlmm-sdk math module "
                "is not mirrored; pass variable_fee_policy='documented' to quote "
                "with the documented formula under an explicit assurance gap"
            )
        variable_applied = True

    token_x_in = swap_for_y
    remaining = amount_in
    total_out = 0
    total_fee = 0
    total_protocol = 0
    active_id = pair.active_id
    bins_used: list[int] = []
    arrays_used: list[str] = []
    walked = 0

    while remaining > 0:
        walked += 1
        if walked > MAX_BINS_WALKED:
            raise DlmmCaptureError("bounded bin-walk computation limit exceeded")
        array_index = find_next_bin_array_index_with_liquidity(
            swap_for_y, active_id, pair.bin_array_bitmap, extension
        )
        if array_index is None:
            raise DlmmCaptureError(
                "BLOCKED(INSUFFICIENT_LIQUIDITY_FOR_DIRECTION): no initialized "
                "bin array remains in the swap direction"
            )
        bin_array = arrays_by_index.get(array_index)
        if bin_array is None:
            raise DlmmCaptureError(f"BLOCKED(MISSING_BIN_ARRAY) index={array_index}")
        if bin_array.address not in arrays_used:
            arrays_used.append(bin_array.address)
        if not is_bin_id_within_bin_array(active_id, array_index):
            raise DlmmCaptureError("active id outside the located bin array")
        bin_ = bin_array.bins[bin_offset_in_bin_array(active_id, array_index)]
        out_capacity = bin_.amount_y if token_x_in else bin_.amount_x
        if out_capacity > 0:
            v_parameters = update_volatility_accumulator(
                v_parameters, s_parameters, active_id
            )
            fee_rate = base_rate
            if variable_applied:
                fee_rate += variable_fee_rate(
                    s_parameters, v_parameters.volatility_accumulator, pair.bin_step
                )
            if fee_rate >= FEE_PRECISION:
                raise DlmmCaptureError("total fee rate at or above FEE_PRECISION")
            price = bin_.price
            if price == 0:
                raise DlmmCaptureError("initialized bin with zero price")
            gross_used, out, fee, protocol = _bin_step(
                remaining,
                out_capacity,
                price,
                token_x_in=token_x_in,
                fee_rate=fee_rate,
                fee_on_input=fee_on_input,
                protocol_share=s_parameters.protocol_share,
            )
            if gross_used == 0 and out == 0 and fee == 0:
                raise DlmmCaptureError("bin step made no progress")
            if gross_used > remaining:
                raise DlmmCaptureError("bin step consumed more than remaining input")
            remaining -= gross_used
            total_out += out
            total_fee += fee
            total_protocol += protocol
            bins_used.append(active_id)
        if remaining > 0:
            active_id = active_id - 1 if swap_for_y else active_id + 1
            if not s_parameters.min_bin_id <= active_id <= s_parameters.max_bin_id:
                raise DlmmCaptureError(
                    "BLOCKED(INSUFFICIENT_LIQUIDITY_FOR_DIRECTION): walked past "
                    "the pair's supported bin range"
                )

    lp_fee = total_fee - total_protocol
    if lp_fee < 0:
        raise DlmmCaptureError("fee split underflow")
    if remaining != 0:
        raise DlmmCaptureError("internal error: input left after complete walk")
    return DlmmExactInQuote(
        amount_in,
        remaining,
        total_out,
        total_fee,
        total_protocol,
        lp_fee,
        swap_for_y,
        pair.active_id,
        active_id,
        tuple(bins_used),
        tuple(arrays_used),
        fee_on_input,
        variable_applied,
        MATH_PROVENANCE,
    )
