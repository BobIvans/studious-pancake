"""R03-A: unsigned Jupiter Lend flashloan borrow/payback builder.

Sender-free offline builder bound to the pinned Jupiter Lend flashloan IDL in
``src/lending/jupiter_lend.py`` (read-only import; that module owns the ABI
constants, discriminators and account layout).  This builder only converts the
pinned unsigned borrow/payback instructions into frozen R03-00 conformance DTOs.

Safety invariants (never violated by this module):
- no signer, no message compilation with signing material, no send/submit;
- no ATA/account creation: an unconfirmed signer borrow token account is
  ``BLOCKED_INPUT_REQUIRED`` with ``R03_NEEDS_ACCOUNT_SETUP`` — setup itself is
  a separate human decision, never performed here;
- ``build_status`` never claims live capacity: every built plan stays
  ``BUILT_OFFLINE_UNQUALIFIED`` with ``capacity_status=NOT_EVALUATED``.
"""

from __future__ import annotations

import hashlib
from typing import Sequence

from solders.instruction import Instruction

from src.lending.financing import FinancingEvidence
from src.lending.jupiter_lend import (
    FLASHLOAN_BORROW_DISCRIMINATOR,
    FLASHLOAN_PAYBACK_DISCRIMINATOR,
    JUPITER_LEND_FLASHLOAN_PROGRAM_ID,
    JupiterLendFlashloanAccounts,
    build_flashloan_borrow_instruction,
    build_flashloan_payback_instruction,
)
from src.lending.unsigned_builders.contract import (
    AccountMetaSpec,
    BuildStatus,
    BuilderSourcePin,
    BookendKind,
    CapacityStatus,
    ConformanceErrorCode,
    ConformanceViolation,
    FinalizedUnsignedSolanaPlan,
    SequenceItem,
    UnsignedBorrowPlan,
    UnsignedRepayPlan,
    UnsignedSolanaBookend,
    UnsignedBuilderError,
    finalize_unsigned_solana_plan,
)

JUPITER_BUILDER_PROVIDER = "jupiter-lend"
JUPITER_BUILDER_CHAIN = "solana"

JUPITER_BORROW_DISCRIMINATOR_HEX = FLASHLOAN_BORROW_DISCRIMINATOR.hex()
JUPITER_PAYBACK_DISCRIMINATOR_HEX = FLASHLOAN_PAYBACK_DISCRIMINATOR.hex()

JUPITER_BUILDER_SOURCE_PIN = BuilderSourcePin(
    provider=JUPITER_BUILDER_PROVIDER,
    chain=JUPITER_BUILDER_CHAIN,
    repository="https://github.com/jup-ag/jupiter-lend",
    commit="33a22cf7a5bfdd32ab1712dda4adfbeb9b348ad9",
    version="0.1.4",
    license_label="MIT (jup-ag/jupiter-lend IDL, pinned blob "
    "0d0ae6d624b33355315e98baaf0a5d00d317beb8)",
    source_paths=("target/idl/flashloan.json",),
    blob_sha1s=("0d0ae6d624b33355315e98baaf0a5d00d317beb8",),
    verified_offline=True,
)


def _require_state_fingerprint(value: str) -> str:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            JUPITER_BUILDER_PROVIDER,
            "state_fingerprint must be a lowercase sha256 of the provider state",
        )
    return value


def _bind_evidence(evidence: FinancingEvidence | None) -> None:
    if evidence is None:
        return
    if evidence.lender_id != JUPITER_BUILDER_PROVIDER:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PROGRAM_ID_MISMATCH,
            JUPITER_BUILDER_PROVIDER,
            f"evidence lender {evidence.lender_id} is not {JUPITER_BUILDER_PROVIDER}",
        )
    if evidence.program_id != str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID):
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PROGRAM_ID_MISMATCH,
            JUPITER_BUILDER_PROVIDER,
            "FinancingEvidence program differs from the pinned Jupiter Lend program",
        )


def _bookend_from_instruction(
    instruction: Instruction,
    kind: BookendKind,
    amount: int,
) -> UnsignedSolanaBookend:
    discriminator = (
        FLASHLOAN_BORROW_DISCRIMINATOR
        if kind is BookendKind.BORROW
        else FLASHLOAN_PAYBACK_DISCRIMINATOR
    )
    return UnsignedSolanaBookend(
        kind=kind,
        program_id=str(instruction.program_id),
        discriminator_hex=discriminator.hex(),
        data_hex=bytes(instruction.data).hex(),
        account_metas=tuple(
            AccountMetaSpec(
                pubkey=str(meta.pubkey),
                is_signer=meta.is_signer,
                is_writable=meta.is_writable,
            )
            for meta in instruction.accounts
        ),
        amount_base_units=amount,
    )


def _needs_account_setup_blocker() -> ConformanceViolation:
    return ConformanceViolation(
        code=ConformanceErrorCode.NEEDS_ACCOUNT_SETUP,
        message=(
            "signer borrow token account existence is not confirmed offline; "
            "missing ATA is NEEDS_ACCOUNT_SETUP, never silent creation"
        ),
        provider=JUPITER_BUILDER_PROVIDER,
    )


def build_jupiter_lend_borrow_plan(
    *,
    accounts: JupiterLendFlashloanAccounts,
    amount: int,
    state_fingerprint: str,
    borrow_token_account_confirmed: bool,
    required_repayment_base_units: int | None = None,
    evidence: FinancingEvidence | None = None,
) -> UnsignedBorrowPlan:
    """Build the unsigned borrow bookend plan, or a typed NEEDS_ACCOUNT_SETUP
    blocked plan when the pre-existing destination account is unconfirmed."""

    _bind_evidence(evidence)
    _require_state_fingerprint(state_fingerprint)
    if not borrow_token_account_confirmed:
        return UnsignedBorrowPlan(
            provider=JUPITER_BUILDER_PROVIDER,
            chain=JUPITER_BUILDER_CHAIN,
            source_pin=JUPITER_BUILDER_SOURCE_PIN,
            asset_id=f"spl:{accounts.mint}:{amount}",
            principal_base_units=amount,
            bookend=None,
            required_repayment_base_units=None,
            state_fingerprint=state_fingerprint,
            blockers=(_needs_account_setup_blocker(),),
            build_status=BuildStatus.BLOCKED_INPUT_REQUIRED,
        )
    instruction = build_flashloan_borrow_instruction(accounts, amount)
    bookend = _bookend_from_instruction(instruction, BookendKind.BORROW, amount)
    return UnsignedBorrowPlan(
        provider=JUPITER_BUILDER_PROVIDER,
        chain=JUPITER_BUILDER_CHAIN,
        source_pin=JUPITER_BUILDER_SOURCE_PIN,
        asset_id=f"spl:{accounts.mint}:{amount}",
        principal_base_units=amount,
        bookend=bookend,
        required_repayment_base_units=required_repayment_base_units,
        state_fingerprint=state_fingerprint,
        build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
    )


def build_jupiter_lend_repay_plan(
    *,
    accounts: JupiterLendFlashloanAccounts,
    borrow_plan: UnsignedBorrowPlan,
    state_fingerprint: str,
    borrow_token_account_confirmed: bool,
    evidence: FinancingEvidence | None = None,
) -> UnsignedRepayPlan:
    """Build the matching unsigned payback plan.

    The pinned ABI encodes the payback amount as an explicit u64 and the
    reviewed Jupiter Lend flow requires repayment == borrow amount (admin fee
    pinned 0 is not capacity evidence); any other repayment amount is a typed
    AMOUNT_MISMATCH, never silently encoded.
    """

    _bind_evidence(evidence)
    _require_state_fingerprint(state_fingerprint)
    if borrow_plan.build_status is not BuildStatus.BUILT_OFFLINE_UNQUALIFIED:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE,
            JUPITER_BUILDER_PROVIDER,
            "repay plan requires a built borrow plan",
        )
    if borrow_plan.provider != JUPITER_BUILDER_PROVIDER:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PROGRAM_ID_MISMATCH,
            JUPITER_BUILDER_PROVIDER,
            "borrow plan belongs to another provider",
        )
    assert borrow_plan.bookend is not None
    if not borrow_token_account_confirmed:
        return UnsignedRepayPlan(
            provider=JUPITER_BUILDER_PROVIDER,
            chain=JUPITER_BUILDER_CHAIN,
            source_pin=JUPITER_BUILDER_SOURCE_PIN,
            asset_id=borrow_plan.asset_id,
            bookend=None,
            borrow_bookend=None,
            required_repayment_base_units=None,
            state_fingerprint=state_fingerprint,
            blockers=(_needs_account_setup_blocker(),),
            build_status=BuildStatus.BLOCKED_INPUT_REQUIRED,
        )
    amount = borrow_plan.principal_base_units
    instruction = build_flashloan_payback_instruction(accounts, amount)
    bookend = _bookend_from_instruction(instruction, BookendKind.REPAY, amount)
    return UnsignedRepayPlan(
        provider=JUPITER_BUILDER_PROVIDER,
        chain=JUPITER_BUILDER_CHAIN,
        source_pin=JUPITER_BUILDER_SOURCE_PIN,
        asset_id=borrow_plan.asset_id,
        bookend=bookend,
        borrow_bookend=borrow_plan.bookend,
        required_repayment_base_units=amount,
        state_fingerprint=state_fingerprint,
        build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
    )


def _to_sequence_item(item: SequenceItem | Instruction) -> SequenceItem:
    if isinstance(item, SequenceItem):
        return item
    return SequenceItem.from_solders_instruction(item)


def assemble_jupiter_lend_message(
    *,
    borrow_plan: UnsignedBorrowPlan,
    repay_plan: UnsignedRepayPlan,
    before_borrow: Sequence[SequenceItem | Instruction] = (),
    route_between: Sequence[SequenceItem | Instruction] = (),
    after_repay: Sequence[SequenceItem | Instruction] = (),
) -> FinalizedUnsignedSolanaPlan:
    """Assemble the final unsigned v0-style instruction order and fail closed.

    Order: [before_borrow (e.g. compute budget)] -> borrow bookend ->
    [route_between] -> repay bookend -> [after_repay].  Conformance (bookend
    presence/order, account order, amount equality) is enforced by the frozen
    contract during finalization.
    """

    if borrow_plan.bookend is None or repay_plan.bookend is None:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE,
            JUPITER_BUILDER_PROVIDER,
            "cannot assemble a message from blocked plans",
        )
    sequence: list[SequenceItem] = [_to_sequence_item(item) for item in before_borrow]
    sequence.append(borrow_plan.bookend.to_sequence_item())
    sequence.extend(_to_sequence_item(item) for item in route_between)
    sequence.append(repay_plan.bookend.to_sequence_item())
    sequence.extend(_to_sequence_item(item) for item in after_repay)
    return finalize_unsigned_solana_plan(
        provider=JUPITER_BUILDER_PROVIDER,
        program_id=str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID),
        borrow_plan=borrow_plan,
        repay_plan=repay_plan,
        sequence=sequence,
        borrow_discriminator_hex=JUPITER_BORROW_DISCRIMINATOR_HEX,
        repay_discriminator_hex=JUPITER_PAYBACK_DISCRIMINATOR_HEX,
    )


def jupiter_state_fingerprint(accounts: JupiterLendFlashloanAccounts) -> str:
    """Deterministic fingerprint of the caller-supplied account binding."""

    digest = hashlib.sha256()
    digest.update(str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID).encode("utf-8"))
    for meta in accounts.metas():
        digest.update(bytes(meta.pubkey))
        digest.update(bytes((int(meta.is_signer), int(meta.is_writable))))
    return digest.hexdigest()


__all__ = [
    "JUPITER_BORROW_DISCRIMINATOR_HEX",
    "JUPITER_BUILDER_CHAIN",
    "JUPITER_BUILDER_PROVIDER",
    "JUPITER_BUILDER_SOURCE_PIN",
    "JUPITER_PAYBACK_DISCRIMINATOR_HEX",
    "assemble_jupiter_lend_message",
    "build_jupiter_lend_borrow_plan",
    "build_jupiter_lend_repay_plan",
    "jupiter_state_fingerprint",
]
