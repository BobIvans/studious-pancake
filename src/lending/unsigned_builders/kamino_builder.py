"""R03-B: unsigned Kamino flash borrow/repay plan builder (pinned ABI, offline).

Pinned source: ``@kamino-finance/klend-sdk@13.0.2`` at upstream commit
``3c3a38d4ff9d7cf7b0380a383b81c9cd4f0f58b8`` (MIT).  The generated
``flashBorrowReserveLiquidity.ts`` / ``flashRepayReserveLiquidity.ts`` /
``programId.ts`` codegen modules are pinned byte-exact in the versioned dossier
``docs/integrations/offline/kamino-flash-builder-2026-11-14/`` (git blob SHA1s
recorded there and re-verified offline by its ``verify_offline_bundle.py``);
the reserve fee layout (``ReserveFees.ts``) and ``Fraction`` fixed-point
semantics remain pinned by the earlier R-02 offline kit.  This builder:

- emits the exact pinned flash borrow/repay ABI offline: the codegen
  discriminators (``87e734a70734d4c1`` / ``b97500cb60f5b4ba``), the fixed
  12-slot ordered account metas (role-for-role, including the codegen
  optional-referrer ``None`` -> program-address semantics), ``u64``
  ``liquidityAmount`` (little-endian) and the repay ``u8``
  ``borrowInstructionIndex``;
- resolves the repay's absolute borrow index only against the final ordering
  (``resolve_absolute_borrow_index`` / ``retarget_borrow_index``) and
  fail-closes in :func:`assemble_kamino_flash_message` when the embedded index
  does not match the finalized sequence;
- never creates obligations or ATAs (``R03_NEEDS_ACCOUNT_SETUP`` instead);
- never signs, sends, submits, enables a live provider, or claims capital
  capacity: ``build_status`` stays ``BUILT_OFFLINE_UNQUALIFIED`` and
  ``capacity_status`` stays ``NOT_EVALUATED``.  Exact onchain fee settlement
  stays ``UNKNOWN`` (recorded via ``onchain_rounding_known=False``), never
  coerced to zero.

There is no provider dispatch registry in the frozen R03-00 contract package:
provider builders are imported directly by their consumers (see
``src/lending/unsigned_builders/__init__.py`` which re-exports only the
frozen contract).  This module therefore needs no additive registration; it
is consumed as ``src.lending.unsigned_builders.kamino_builder``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Sequence

from src.lending.unsigned_builders.contract import (
    AccountMetaSpec,
    BookendKind,
    BuildStatus,
    BuilderSourcePin,
    ConformanceErrorCode,
    ConformanceViolation,
    FinalizedUnsignedSolanaPlan,
    SequenceItem,
    U64_MAX,
    U8_MAX,
    UnsignedBorrowPlan,
    UnsignedRepayPlan,
    UnsignedSolanaBookend,
    UnsignedBuilderError,
    finalize_unsigned_solana_plan,
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
    license_label="MIT (package.json, pinned blobs d3e4062acbfac32d9fdb48604832762c33f31c0e / "
    "369cd6ac39e4f160d6482790050c469a6d10d811 / "
    "e41d81b7d076e2c85c24bc3b45803c2b974a9b2c / "
    "54358dac24be146a1f7b310d2851dd7b61d69789 / "
    "0020a1293fd0bced5987b2429a6b5ed8e2f693e8)",
    source_paths=(
        "src/@codegen/klend/instructions/flashBorrowReserveLiquidity.ts",
        "src/@codegen/klend/instructions/flashRepayReserveLiquidity.ts",
        "src/@codegen/klend/programId.ts",
        "src/@codegen/klend/types/ReserveFees.ts",
        "src/classes/fraction.ts",
    ),
    blob_sha1s=(
        "d3e4062acbfac32d9fdb48604832762c33f31c0e",
        "369cd6ac39e4f160d6482790050c469a6d10d811",
        "e41d81b7d076e2c85c24bc3b45803c2b974a9b2c",
        "54358dac24be146a1f7b310d2851dd7b61d69789",
        "0020a1293fd0bced5987b2429a6b5ed8e2f693e8",
    ),
    verified_offline=True,
)

#: Generated flash borrow/repay instruction modules are pinned byte-exact in
#: docs/integrations/offline/kamino-flash-builder-2026-11-14/ (verified offline).
KAMINO_FLASH_BORROW_ABI_PINNED = True
KAMINO_FLASH_REPAY_ABI_PINNED = True

#: Pinned codegen discriminators (see the vendored instruction modules).
KAMINO_FLASH_BORROW_DISCRIMINATOR = bytes((135, 231, 52, 167, 7, 52, 212, 193))
KAMINO_FLASH_BORROW_DISCRIMINATOR_HEX = KAMINO_FLASH_BORROW_DISCRIMINATOR.hex()
KAMINO_FLASH_REPAY_DISCRIMINATOR = bytes((185, 117, 0, 203, 96, 245, 180, 186))
KAMINO_FLASH_REPAY_DISCRIMINATOR_HEX = KAMINO_FLASH_REPAY_DISCRIMINATOR.hex()

#: Pinned Fraction semantics: fixed-point scale 2^60; MAX_F_BN = 2^128 - 1.
KAMINO_ONE_SF = 1 << 60
KAMINO_MAX_F = (1 << 128) - 1

#: Pinned ReserveFees borsh layout: u64 originationFeeSf, u64 flashLoanFeeSf,
#: u8[8] padding (24 bytes total).
_KAMINO_RESERVE_FEES_FORMAT = "<QQ8s"
_KAMINO_RESERVE_FEES_SIZE = struct.calcsize(_KAMINO_RESERVE_FEES_FORMAT)

#: Pinned repay data layout: discriminator(8) + u64 liquidityAmount + u8
#: borrowInstructionIndex (17 bytes total).
_KAMINO_FLASH_REPAY_DATA_FORMAT = "<QB"
_KAMINO_FLASH_REPAY_DATA_SIZE = 8 + struct.calcsize(_KAMINO_FLASH_REPAY_DATA_FORMAT)

#: Pinned codegen fact: neither flash instruction carries an Obligation
#: account (no Obligation in either 12-slot account list).
KAMINO_FLASH_IX_NO_OBLIGATION_ACCOUNT_NOTE = (
    "no Obligation account appears in the pinned flashBorrowReserveLiquidity/"
    "flashRepayReserveLiquidity codegen account lists (klend-sdk@13.0.2); "
    "obligation creation is never part of the flash path"
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


@dataclass(frozen=True, slots=True)
class KaminoFlashAccounts:
    """Caller-supplied flash-bracket account binding (offline, synthetic or real).

    Slot semantics follow the pinned codegen interfaces exactly:

    - ``reserve_liquidity_vault`` is ``reserveSourceLiquidity`` on borrow and
      ``reserveDestinationLiquidity`` on repay (the same supply vault: funds
      leave and must return);
    - ``user_liquidity_account`` is ``userDestinationLiquidity`` on borrow and
      ``userSourceLiquidity`` on repay (the same user token account);
    - ``instructions_sysvar`` is the codegen ``sysvarInfo`` slot (the caller
      supplies it explicitly; this module never hardcodes sysvar addresses);
    - ``referrer_token_state`` / ``referrer_account`` mirror the codegen
      ``Option<Address>`` slots: ``None`` encodes the pinned ``None`` branch
      (program address, readonly), a pubkey encodes the ``Some`` branch
      (writable, in slot order).
    """

    user_transfer_authority: str
    lending_market_authority: str
    lending_market: str
    reserve: str
    reserve_liquidity_mint: str
    reserve_liquidity_vault: str
    user_liquidity_account: str
    reserve_liquidity_fee_receiver: str
    instructions_sysvar: str
    token_program: str
    referrer_token_state: str | None = None
    referrer_account: str | None = None

    def _referrer_meta(self, value: str | None) -> AccountMetaSpec:
        if value is None:
            return AccountMetaSpec(
                pubkey=KAMINO_KLEND_PROGRAM_ID, is_signer=False, is_writable=False
            )
        return AccountMetaSpec(pubkey=value, is_signer=False, is_writable=True)

    def ordered_metas(self) -> tuple[AccountMetaSpec, ...]:
        """Exact pinned 12-slot ordered metas (identical for borrow and repay)."""

        return (
            AccountMetaSpec(
                pubkey=self.user_transfer_authority, is_signer=True, is_writable=False
            ),
            AccountMetaSpec(
                pubkey=self.lending_market_authority,
                is_signer=False,
                is_writable=False,
            ),
            AccountMetaSpec(
                pubkey=self.lending_market, is_signer=False, is_writable=False
            ),
            AccountMetaSpec(pubkey=self.reserve, is_signer=False, is_writable=True),
            AccountMetaSpec(
                pubkey=self.reserve_liquidity_mint, is_signer=False, is_writable=False
            ),
            AccountMetaSpec(
                pubkey=self.reserve_liquidity_vault, is_signer=False, is_writable=True
            ),
            AccountMetaSpec(
                pubkey=self.user_liquidity_account, is_signer=False, is_writable=True
            ),
            AccountMetaSpec(
                pubkey=self.reserve_liquidity_fee_receiver,
                is_signer=False,
                is_writable=True,
            ),
            self._referrer_meta(self.referrer_token_state),
            self._referrer_meta(self.referrer_account),
            AccountMetaSpec(
                pubkey=self.instructions_sysvar, is_signer=False, is_writable=False
            ),
            AccountMetaSpec(
                pubkey=self.token_program, is_signer=False, is_writable=False
            ),
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
    if conservative_repayment > U64_MAX:
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


def _require_u64_liquidity_amount(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            KAMINO_BUILDER_PROVIDER,
            "liquidityAmount must be a positive integer",
        )
    if value > U64_MAX:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            KAMINO_BUILDER_PROVIDER,
            "liquidityAmount exceeds u64",
        )


def encode_kamino_flash_borrow_data(liquidity_amount: int) -> bytes:
    """Pinned borrow data: discriminator(8) + u64 liquidityAmount LE (16 bytes)."""

    _require_u64_liquidity_amount(liquidity_amount)
    return KAMINO_FLASH_BORROW_DISCRIMINATOR + struct.pack("<Q", liquidity_amount)


def encode_kamino_flash_repay_data(
    liquidity_amount: int, borrow_instruction_index: int
) -> bytes:
    """Pinned repay data: discriminator(8) + u64 LE + u8 borrow index (17 bytes)."""

    _require_u64_liquidity_amount(liquidity_amount)
    if type(borrow_instruction_index) is not int or not 0 <= borrow_instruction_index:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            KAMINO_BUILDER_PROVIDER,
            "borrowInstructionIndex must be a non-negative integer",
        )
    if borrow_instruction_index > U8_MAX:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.REPAY_INDEX_OVERFLOW,
            KAMINO_BUILDER_PROVIDER,
            f"borrowInstructionIndex {borrow_instruction_index} does not fit u8",
        )
    return KAMINO_FLASH_REPAY_DISCRIMINATOR + struct.pack(
        _KAMINO_FLASH_REPAY_DATA_FORMAT, liquidity_amount, borrow_instruction_index
    )


def build_kamino_flash_borrow_bookend(
    accounts: KaminoFlashAccounts,
    liquidity_amount: int,
) -> UnsignedSolanaBookend:
    """Exact pinned unsigned flash-borrow instruction as a borrow bookend."""

    data = encode_kamino_flash_borrow_data(liquidity_amount)
    return UnsignedSolanaBookend(
        kind=BookendKind.BORROW,
        program_id=KAMINO_KLEND_PROGRAM_ID,
        discriminator_hex=KAMINO_FLASH_BORROW_DISCRIMINATOR_HEX,
        data_hex=data.hex(),
        account_metas=accounts.ordered_metas(),
        amount_base_units=liquidity_amount,
    )


def build_kamino_flash_repay_bookend(
    accounts: KaminoFlashAccounts,
    liquidity_amount: int,
    borrow_instruction_index: int,
) -> UnsignedSolanaBookend:
    """Exact pinned unsigned flash-repay instruction as a repay bookend.

    ``borrow_instruction_index`` must already be the absolute index of the
    flash-borrow instruction in the FINAL compiled order (after compute-budget
    and route insertion); :func:`assemble_kamino_flash_message` re-verifies it
    against the finalized sequence.
    """

    data = encode_kamino_flash_repay_data(liquidity_amount, borrow_instruction_index)
    return UnsignedSolanaBookend(
        kind=BookendKind.REPAY,
        program_id=KAMINO_KLEND_PROGRAM_ID,
        discriminator_hex=KAMINO_FLASH_REPAY_DISCRIMINATOR_HEX,
        data_hex=data.hex(),
        account_metas=accounts.ordered_metas(),
        amount_base_units=liquidity_amount,
    )


def _operator_account_input_required_blocker(target: str) -> ConformanceViolation:
    return ConformanceViolation(
        code=ConformanceErrorCode.OPERATOR_ACCOUNT_INPUT_REQUIRED,
        message=(
            f"{target} is required to build the pinned Kamino flash "
            "instruction; no account binding, no instruction bytes"
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


def _borrow_index_input_required_blocker() -> ConformanceViolation:
    return ConformanceViolation(
        code=ConformanceErrorCode.INVALID_INPUT,
        message=(
            "borrow_instruction_index (absolute u8 index of the flash borrow "
            "instruction in the final ordering) is required to encode the "
            "repay; refusing to assume a value"
        ),
        provider=KAMINO_BUILDER_PROVIDER,
    )


def build_kamino_flash_borrow_plan(
    *,
    principal_base_units: int,
    flash_loan_fee_sf: int,
    state_fingerprint: str,
    destination_token_account_confirmed: bool,
    accounts: KaminoFlashAccounts | None = None,
) -> UnsignedBorrowPlan:
    """Build the unsigned flash-borrow plan, or a typed blocked plan.

    - ``accounts`` binding supplied and the destination account confirmed ->
      ``BUILT_OFFLINE_UNQUALIFIED`` with the exact pinned instruction bytes;
    - missing binding -> ``R03_OPERATOR_ACCOUNT_INPUT_REQUIRED``;
    - unconfirmed destination -> ``R03_NEEDS_ACCOUNT_SETUP`` (never creation).
    """

    projection = compute_flash_loan_repayment(principal_base_units, flash_loan_fee_sf)
    blockers: list[ConformanceViolation] = []
    if accounts is None:
        blockers.append(
            _operator_account_input_required_blocker("a KaminoFlashAccounts binding")
        )
    if not destination_token_account_confirmed:
        blockers.append(_needs_account_setup_blocker())
    if blockers:
        return UnsignedBorrowPlan(
            provider=KAMINO_BUILDER_PROVIDER,
            chain=KAMINO_BUILDER_CHAIN,
            source_pin=KAMINO_BUILDER_SOURCE_PIN,
            asset_id=f"klend:{KAMINO_KLEND_PROGRAM_ID}:{projection.principal_base_units}",
            principal_base_units=projection.principal_base_units,
            bookend=None,
            required_repayment_base_units=projection.conservative_required_repayment,
            state_fingerprint=state_fingerprint,
            blockers=tuple(blockers),
            build_status=BuildStatus.BLOCKED_INPUT_REQUIRED,
        )
    assert accounts is not None
    bookend = build_kamino_flash_borrow_bookend(accounts, principal_base_units)
    return UnsignedBorrowPlan(
        provider=KAMINO_BUILDER_PROVIDER,
        chain=KAMINO_BUILDER_CHAIN,
        source_pin=KAMINO_BUILDER_SOURCE_PIN,
        asset_id=f"klend:{KAMINO_KLEND_PROGRAM_ID}:{projection.principal_base_units}",
        principal_base_units=projection.principal_base_units,
        bookend=bookend,
        required_repayment_base_units=projection.conservative_required_repayment,
        state_fingerprint=state_fingerprint,
        build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
    )


def build_kamino_flash_repay_plan(
    *,
    borrow_plan: UnsignedBorrowPlan,
    flash_loan_fee_sf: int,
    state_fingerprint: str,
    destination_token_account_confirmed: bool,
    accounts: KaminoFlashAccounts | None = None,
    borrow_instruction_index: int | None = None,
) -> UnsignedRepayPlan:
    """Build the matching unsigned flash-repay plan bound to the borrow plan.

    The repay instruction embeds the absolute borrow instruction index as
    ``u8``; it must be the FINAL index (after compute-budget and route
    insertion) — supply it via ``borrow_instruction_index`` and let
    :func:`assemble_kamino_flash_message` verify it against the finalized
    sequence.  The repay bookend must bind the same ordered metas as the
    borrow bookend (frozen contract ``check_account_order``), which encodes
    the flash bracket: the same supply vault and the same user token account.
    """

    if borrow_plan.provider != KAMINO_BUILDER_PROVIDER:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PROGRAM_ID_MISMATCH,
            KAMINO_BUILDER_PROVIDER,
            "borrow plan belongs to another provider",
        )
    if borrow_plan.build_status is BuildStatus.BUILT_OFFLINE_UNQUALIFIED:
        bookend = borrow_plan.bookend
        if (
            bookend is None
            or bookend.discriminator_hex != KAMINO_FLASH_BORROW_DISCRIMINATOR_HEX
            or bookend.program_id != KAMINO_KLEND_PROGRAM_ID
        ):
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE,
                KAMINO_BUILDER_PROVIDER,
                "borrow plan was not built by the pinned Kamino flash builder; "
                "refusing to bind a repay to foreign instruction bytes",
            )
    projection = compute_flash_loan_repayment(
        borrow_plan.principal_base_units, flash_loan_fee_sf
    )
    blockers: list[ConformanceViolation] = []
    if accounts is None:
        blockers.append(
            _operator_account_input_required_blocker("a KaminoFlashAccounts binding")
        )
    if not destination_token_account_confirmed:
        blockers.append(_needs_account_setup_blocker())
    if borrow_plan.build_status is BuildStatus.BUILT_OFFLINE_UNQUALIFIED:
        if borrow_instruction_index is None:
            blockers.append(_borrow_index_input_required_blocker())
    if (
        blockers
        or borrow_plan.build_status is not BuildStatus.BUILT_OFFLINE_UNQUALIFIED
    ):
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
            blockers=tuple(blockers) or (_borrow_index_input_required_blocker(),),
            build_status=BuildStatus.BLOCKED_INPUT_REQUIRED,
        )
    assert accounts is not None and borrow_instruction_index is not None
    assert borrow_plan.bookend is not None
    repay_bookend = build_kamino_flash_repay_bookend(
        accounts, borrow_plan.principal_base_units, borrow_instruction_index
    )
    return UnsignedRepayPlan(
        provider=KAMINO_BUILDER_PROVIDER,
        chain=KAMINO_BUILDER_CHAIN,
        source_pin=KAMINO_BUILDER_SOURCE_PIN,
        asset_id=borrow_plan.asset_id,
        bookend=repay_bookend,
        borrow_bookend=borrow_plan.bookend,
        required_repayment_base_units=projection.conservative_required_repayment,
        borrow_index_u8_required=True,
        state_fingerprint=state_fingerprint,
        build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
    )


def _to_sequence_item(item: SequenceItem | UnsignedSolanaBookend) -> SequenceItem:
    if isinstance(item, SequenceItem):
        return item
    if isinstance(item, UnsignedSolanaBookend):
        return item.to_sequence_item()
    return SequenceItem.from_solders_instruction(item)


def assemble_kamino_flash_message(
    *,
    borrow_plan: UnsignedBorrowPlan,
    repay_plan: UnsignedRepayPlan,
    before_borrow: Sequence[SequenceItem | UnsignedSolanaBookend] = (),
    route_between: Sequence[SequenceItem | UnsignedSolanaBookend] = (),
    after_repay: Sequence[SequenceItem | UnsignedSolanaBookend] = (),
) -> FinalizedUnsignedSolanaPlan:
    """Assemble the final unsigned instruction order and fail closed.

    Order: [before_borrow (e.g. compute budget)] -> flash borrow ->
    [route_between] -> flash repay -> [after_repay].  Beyond the frozen
    contract finalization (bookend presence/order, identical ordered metas,
    amount equality, u8 range), this verifies the Kamino-specific invariant:
    the repay data's embedded ``borrowInstructionIndex`` u8 equals the
    absolute borrow index in the FINAL ordering.
    """

    if borrow_plan.bookend is None or repay_plan.bookend is None:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE,
            KAMINO_BUILDER_PROVIDER,
            "cannot assemble a message from blocked plans",
        )
    sequence: list[SequenceItem] = [_to_sequence_item(item) for item in before_borrow]
    sequence.append(borrow_plan.bookend.to_sequence_item())
    sequence.extend(_to_sequence_item(item) for item in route_between)
    sequence.append(repay_plan.bookend.to_sequence_item())
    sequence.extend(_to_sequence_item(item) for item in after_repay)
    finalized = finalize_unsigned_solana_plan(
        provider=KAMINO_BUILDER_PROVIDER,
        program_id=KAMINO_KLEND_PROGRAM_ID,
        borrow_plan=borrow_plan,
        repay_plan=repay_plan,
        sequence=sequence,
        borrow_discriminator_hex=KAMINO_FLASH_BORROW_DISCRIMINATOR_HEX,
        repay_discriminator_hex=KAMINO_FLASH_REPAY_DISCRIMINATOR_HEX,
    )
    raw = bytes.fromhex(repay_plan.bookend.data_hex)
    if len(raw) != _KAMINO_FLASH_REPAY_DATA_SIZE:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            KAMINO_BUILDER_PROVIDER,
            f"repay data must be exactly {_KAMINO_FLASH_REPAY_DATA_SIZE} bytes",
        )
    _liquidity_amount, embedded_index = struct.unpack(
        _KAMINO_FLASH_REPAY_DATA_FORMAT, raw[8:]
    )
    if embedded_index != finalized.certificate.borrow_index:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            KAMINO_BUILDER_PROVIDER,
            "repay borrowInstructionIndex "
            f"{embedded_index} does not match the final absolute borrow index "
            f"{finalized.certificate.borrow_index}; re-resolve the index "
            "after any ordering shift",
        )
    return finalized


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

    matches = [
        index for index, item in enumerate(sequence) if item == borrow_instruction
    ]
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
    if index > U8_MAX:
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
    if retargeted > U8_MAX:
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
    "KAMINO_FLASH_BORROW_ABI_PINNED",
    "KAMINO_FLASH_BORROW_DISCRIMINATOR",
    "KAMINO_FLASH_BORROW_DISCRIMINATOR_HEX",
    "KAMINO_FLASH_IX_NO_OBLIGATION_ACCOUNT_NOTE",
    "KAMINO_FLASH_REPAY_ABI_PINNED",
    "KAMINO_FLASH_REPAY_DISCRIMINATOR",
    "KAMINO_FLASH_REPAY_DISCRIMINATOR_HEX",
    "KAMINO_KLEND_PROGRAM_ID",
    "KAMINO_MAX_F",
    "KAMINO_ONE_SF",
    "KaminoFeeProjection",
    "KaminoFlashAccounts",
    "assemble_kamino_flash_message",
    "build_kamino_flash_borrow_bookend",
    "build_kamino_flash_borrow_plan",
    "build_kamino_flash_repay_bookend",
    "build_kamino_flash_repay_plan",
    "compute_flash_loan_repayment",
    "decode_reserve_fees",
    "encode_kamino_flash_borrow_data",
    "encode_kamino_flash_repay_data",
    "resolve_absolute_borrow_index",
    "retarget_borrow_index",
]
