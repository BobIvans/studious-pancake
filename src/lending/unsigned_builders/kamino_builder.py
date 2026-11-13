"""R03-B: unsigned Kamino flash borrow/repay plan builder (typed-ABI-gated).

Pinned source: ``@kamino-finance/klend-sdk@13.0.2`` at upstream commit
``3c3a38d4ff9d7cf7b0380a383b81c9cd4f0f58b8`` (MIT).  The offline kit vendors
reserve state, the ``ReserveFees`` borsh layout and ``Fraction`` fixed-point
semantics, but does **not** vendor the generated
``flashBorrowReserveLiquidity.ts`` / ``flashRepayReserveLiquidity.ts``
instruction modules or their transitive dependencies.  Per the frozen R03-B
policy this builder therefore:

- never guesses the flash borrow/repay instruction ABI (discriminators, account
  metas) — any raw instruction build is a typed
  ``R03_MISSING_PINNED_BUILDER_ABI`` blocked plan with no fabricated bytes;
- owns only what the pinned sources specify exactly: the ``ReserveFees``
  borsh decode (originationFeeSf u64 / flashLoanFeeSf u64 / u8[8] padding),
  Fraction fixed-point fee projection semantics, and the repay-to-borrow
  absolute-index-as-u8 contract required after final ordering;
- never creates obligations or ATAs (``R03_NEEDS_ACCOUNT_SETUP`` instead).

``build_status`` is separate from ``capacity_status``: nothing here is live
capital evidence.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Sequence

from src.lending.unsigned_builders.contract import (
    BuildStatus,
    BuilderSourcePin,
    ConformanceErrorCode,
    ConformanceViolation,
    SequenceItem,
    UnsignedBorrowPlan,
    UnsignedRepayPlan,
    UnsignedBuilderError,
)

KAMINO_BUILDER_PROVIDER = "kamino"
KAMINO_BUILDER_CHAIN = "solana"
KAMINO_KLEND_PROGRAM_ID = "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD"

KAMINO_BUILDER_SOURCE_PIN = BuilderSourcePin(
    provider=KAMINO_BUILDER_PROVIDER,
    chain=KAMINO_BUILDER_CHAIN,
    repository="https://github.com/Kamino-Finance/klend-sdk",
    commit="3c3a38d4ff9d7cf7b0380a383b81c9cd4f0f58b8",
    version="13.0.2",
    license_label="MIT (package.json, pinned blobs 54358dac24be146a1f7b310d2851dd7b61d69789 / "
    "0020a1293fd0bced5987b2429a6b5ed8e2f693e8)",
    source_paths=(
        "src/@codegen/klend/types/ReserveFees.ts",
        "src/classes/fraction.ts",
    ),
    blob_sha1s=(
        "54358dac24be146a1f7b310d2851dd7b61d69789",
        "0020a1293fd0bced5987b2429a6b5ed8e2f693e8",
    ),
    verified_offline=True,
)

#: Generated flash-borrow/flash-repay instruction modules are absent from the
#: pinned offline kit.  Building their ABI would be guessing -> fail closed.
KAMINO_FLASH_BORROW_ABI_PINNED = False
KAMINO_FLASH_REPAY_ABI_PINNED = False

#: Pinned Fraction semantics: fixed-point scale 2^60; MAX_F_BN = 2^128 - 1.
KAMINO_ONE_SF = 1 << 60
KAMINO_MAX_F = (1 << 128) - 1

#: Pinned ReserveFees borsh layout: u64 originationFeeSf, u64 flashLoanFeeSf,
#: u8[8] padding (24 bytes total).
_KAMINO_RESERVE_FEES_FORMAT = "<QQ8s"
_KAMINO_RESERVE_FEES_SIZE = struct.calcsize(_KAMINO_RESERVE_FEES_FORMAT)

#: Documented (reviewed klend source) fact from R03_SHADOW_BUILDERS: the flash
#: instructions do not require an Obligation account.  Documentation note only,
#: not a substitute for the missing generated ABI.
KAMINO_FLASH_IX_NO_OBLIGATION_ACCOUNT_NOTE = (
    "no Obligation account is required in Kamino FLASH instructions per the "
    "reviewed pinned klend source notes (R03_SHADOW_BUILDERS)"
)


@dataclass(frozen=True, slots=True)
class KaminoFeeProjection:
    """Exact fixed-point flash-loan fee projection from pinned semantics.

    ``floor_required_repayment`` and ``conservative_required_repayment`` bound
    the on-chain rounding, which is **not** claimed known here
    (``onchain_rounding_known`` stays False; unknown is never coerced to zero).
    """

    principal_base_units: int
    flash_loan_fee_sf: int
    fee_floor: int
    fee_ceil: int
    floor_required_repayment: int
    conservative_required_repayment: int
    onchain_rounding_known: bool = False

    def __post_init__(self) -> None:
        if type(self.principal_base_units) is not int or self.principal_base_units <= 0:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.INVALID_INPUT,
                KAMINO_BUILDER_PROVIDER,
                "principal must be a positive integer",
            )
        if type(self.flash_loan_fee_sf) is not int or not 0 <= self.flash_loan_fee_sf:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.INVALID_INPUT,
                KAMINO_BUILDER_PROVIDER,
                "flash_loan_fee_sf must be a non-negative integer",
            )
        if self.flash_loan_fee_sf > KAMINO_MAX_F:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.INVALID_INPUT,
                KAMINO_BUILDER_PROVIDER,
                "flash_loan_fee_sf exceeds Fraction MAX_F_BN (2^128 - 1)",
            )


def compute_flash_loan_repayment(
    principal_base_units: int,
    flash_loan_fee_sf: int,
) -> KaminoFeeProjection:
    """Project the required flash-loan repayment from pinned Fraction semantics.

    Mirrors the pinned ``Fraction`` fixed-point multiply
    (``floor(a_sf * b_sf / 2^60)``): the fee numerator is
    ``principal * flash_loan_fee_sf`` scaled by 2^60.  Both the floor and the
    ceil of the fee are reported; the conservative repayment (principal +
    ceil-fee) never understates the obligation.  Exact on-chain rounding is
    explicitly recorded as unknown, never assumed.
    """

    if type(principal_base_units) is not int or principal_base_units <= 0:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            KAMINO_BUILDER_PROVIDER,
            "principal must be a positive integer",
        )
    if type(flash_loan_fee_sf) is not int:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            KAMINO_BUILDER_PROVIDER,
            "flash_loan_fee_sf unknown: refusing to assume zero; supply the "
            "pinned ReserveFees.flashLoanFeeSf value",
        )
    if flash_loan_fee_sf < 0 or flash_loan_fee_sf > KAMINO_MAX_F:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            KAMINO_BUILDER_PROVIDER,
            "flash_loan_fee_sf out of pinned Fraction range",
        )
    numerator = principal_base_units * flash_loan_fee_sf
    fee_floor = numerator // KAMINO_ONE_SF
    fee_ceil = (numerator + KAMINO_ONE_SF - 1) // KAMINO_ONE_SF
    floor_repayment = principal_base_units + fee_floor
    conservative_repayment = principal_base_units + fee_ceil
    u64_max = (1 << 64) - 1
    if conservative_repayment > u64_max:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            KAMINO_BUILDER_PROVIDER,
            "conservative repayment exceeds u64",
        )
    return KaminoFeeProjection(
        principal_base_units=principal_base_units,
        flash_loan_fee_sf=flash_loan_fee_sf,
        fee_floor=fee_floor,
        fee_ceil=fee_ceil,
        floor_required_repayment=floor_repayment,
        conservative_required_repayment=conservative_repayment,
    )


def decode_reserve_fees(data: bytes) -> tuple[int, int]:
    """Decode ``(origination_fee_sf, flash_loan_fee_sf)`` from the pinned
    ``ReserveFees`` borsh layout (u64, u64, u8[8]).  Fail-closed on size."""

    raw = bytes(data)
    if len(raw) != _KAMINO_RESERVE_FEES_SIZE:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            KAMINO_BUILDER_PROVIDER,
            f"ReserveFees payload must be exactly {_KAMINO_RESERVE_FEES_SIZE} bytes",
        )
    origination_fee_sf, flash_loan_fee_sf, _padding = struct.unpack(
        _KAMINO_RESERVE_FEES_FORMAT, raw
    )
    return int(origination_fee_sf), int(flash_loan_fee_sf)


def _missing_abi_blocker(target: str) -> ConformanceViolation:
    return ConformanceViolation(
        code=ConformanceErrorCode.MISSING_PINNED_BUILDER_ABI,
        message=(
            f"generated {target} instruction module is absent from the pinned "
            "klend-sdk@13.0.2 offline kit; refusing to guess the builder ABI"
        ),
        provider=KAMINO_BUILDER_PROVIDER,
    )


def _needs_account_setup_blocker() -> ConformanceViolation:
    return ConformanceViolation(
        code=ConformanceErrorCode.NEEDS_ACCOUNT_SETUP,
        message=(
            "expected SPL destination token account is not confirmed to "
            "pre-exist; Kamino flash path requires it without creating accounts"
        ),
        provider=KAMINO_BUILDER_PROVIDER,
    )


def build_kamino_flash_borrow_plan(
    *,
    principal_base_units: int,
    flash_loan_fee_sf: int,
    state_fingerprint: str,
    destination_token_account_confirmed: bool,
) -> UnsignedBorrowPlan:
    """Typed-BLOCKED borrow plan: ABI missing, so no instruction bytes are
    fabricated.  Fee projection and state binding are still recorded."""

    projection = compute_flash_loan_repayment(principal_base_units, flash_loan_fee_sf)
    blockers = [_missing_abi_blocker("flashBorrowReserveLiquidity")]
    if not destination_token_account_confirmed:
        blockers.append(_needs_account_setup_blocker())
    return UnsignedBorrowPlan(
        provider=KAMINO_BUILDER_PROVIDER,
        chain=KAMINO_BUILDER_CHAIN,
        source_pin=KAMINO_BUILDER_SOURCE_PIN,
        asset_id=f"klend:{KAMINO_KLEND_PROGRAM_ID}:{projection.principal_base_units}",
        principal_base_units=principal_base_units,
        bookend=None,
        required_repayment_base_units=projection.conservative_required_repayment,
        state_fingerprint=state_fingerprint,
        blockers=tuple(blockers),
        build_status=BuildStatus.BLOCKED_MISSING_PINNED_BUILDER_ABI,
    )


def build_kamino_flash_repay_plan(
    *,
    borrow_plan: UnsignedBorrowPlan,
    flash_loan_fee_sf: int,
    state_fingerprint: str,
    destination_token_account_confirmed: bool,
) -> UnsignedRepayPlan:
    """Typed-BLOCKED repay plan bound to the blocked borrow plan.

    The repay instruction must reference the exact absolute borrow instruction
    index as ``u8`` after final ordering (see
    :func:`resolve_absolute_borrow_index`); because the generated repay ABI is
    absent, no repay instruction bytes are fabricated here.
    """

    if borrow_plan.provider != KAMINO_BUILDER_PROVIDER:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PROGRAM_ID_MISMATCH,
            KAMINO_BUILDER_PROVIDER,
            "borrow plan belongs to another provider",
        )
    if borrow_plan.build_status is BuildStatus.BUILT_OFFLINE_UNQUALIFIED:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE,
            KAMINO_BUILDER_PROVIDER,
            "Kamino borrow plans can never be built offline without the "
            "pinned generated ABI; a built borrow plan is invalid input",
        )
    projection = compute_flash_loan_repayment(
        borrow_plan.principal_base_units, flash_loan_fee_sf
    )
    blockers = [_missing_abi_blocker("flashRepayReserveLiquidity")]
    if not destination_token_account_confirmed:
        blockers.append(_needs_account_setup_blocker())
    return UnsignedRepayPlan(
        provider=KAMINO_BUILDER_PROVIDER,
        chain=KAMINO_BUILDER_CHAIN,
        source_pin=KAMINO_BUILDER_SOURCE_PIN,
        asset_id=borrow_plan.asset_id,
        bookend=None,
        borrow_bookend=None,
        required_repayment_base_units=projection.conservative_required_repayment,
        borrow_index_u8_required=True,
        state_fingerprint=state_fingerprint,
        blockers=tuple(blockers),
        build_status=BuildStatus.BLOCKED_MISSING_PINNED_BUILDER_ABI,
    )


def resolve_absolute_borrow_index(
    sequence: Sequence[SequenceItem],
    borrow_instruction: SequenceItem,
    *,
    repay_index: int | None = None,
) -> int:
    """Resolve the absolute borrow instruction index in the final message.

    Fail-closed: missing (BOOKEND_MISSING), duplicated (DUPLICATE_BOOKEND),
    beyond u8 (REPAY_INDEX_OVERFLOW), or not strictly before the repay index
    (BOOKEND_ORDER_INVALID).
    """

    matches = [index for index, item in enumerate(sequence) if item == borrow_instruction]
    if len(matches) == 0:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.BOOKEND_MISSING,
            KAMINO_BUILDER_PROVIDER,
            "flash borrow instruction is absent from the final ordering",
        )
    if len(matches) > 1:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.DUPLICATE_BOOKEND,
            KAMINO_BUILDER_PROVIDER,
            f"flash borrow instruction occurs {len(matches)} times; "
            "the repay index reference would be ambiguous",
        )
    index = matches[0]
    if index > 0xFF:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.REPAY_INDEX_OVERFLOW,
            KAMINO_BUILDER_PROVIDER,
            f"absolute borrow index {index} does not fit u8",
        )
    if repay_index is not None and index >= repay_index:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.BOOKEND_ORDER_INVALID,
            KAMINO_BUILDER_PROVIDER,
            "flash borrow must strictly precede the repay instruction",
        )
    return index


def retarget_borrow_index(original_index: int, inserted_before: int) -> int:
    """Retarget the repay-referenced borrow index after route insertion.

    ``inserted_before`` counts instructions added strictly before the borrow
    instruction in the final order (e.g. compute-budget instructions).
    """

    if type(original_index) is not int or original_index < 0:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            KAMINO_BUILDER_PROVIDER,
            "original_index must be a non-negative integer",
        )
    if type(inserted_before) is not int or inserted_before < 0:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            KAMINO_BUILDER_PROVIDER,
            "inserted_before must be a non-negative integer",
        )
    retargeted = original_index + inserted_before
    if retargeted > 0xFF:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.REPAY_INDEX_OVERFLOW,
            KAMINO_BUILDER_PROVIDER,
            f"retargeted borrow index {retargeted} does not fit u8",
        )
    return retargeted


__all__ = [
    "KAMINO_BUILDER_CHAIN",
    "KAMINO_BUILDER_PROVIDER",
    "KAMINO_BUILDER_SOURCE_PIN",
    "KAMINO_FLASH_IX_NO_OBLIGATION_ACCOUNT_NOTE",
    "KAMINO_FLASH_BORROW_ABI_PINNED",
    "KAMINO_FLASH_REPAY_ABI_PINNED",
    "KAMINO_KLEND_PROGRAM_ID",
    "KAMINO_MAX_F",
    "KAMINO_ONE_SF",
    "KaminoFeeProjection",
    "build_kamino_flash_borrow_plan",
    "build_kamino_flash_repay_plan",
    "compute_flash_loan_repayment",
    "decode_reserve_fees",
    "resolve_absolute_borrow_index",
    "retarget_borrow_index",
]
