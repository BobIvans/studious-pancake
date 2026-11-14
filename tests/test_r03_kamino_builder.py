"""R03-B Kamino unsigned builder tests: pinned fee/index semantics + pinned flash ABI.

Offline only (pytest-socket enforced by tests/conftest.py).  Golden bytes are
pinned in tests/fixtures/r03/kamino_flash_abi_golden.json and re-derived from
the pinned klend-sdk@13.0.2 generated instruction modules documented in
docs/integrations/offline/kamino-flash-builder-2026-11-14/.
"""

from __future__ import annotations

import pytest

from src.lending.unsigned_builders.contract import (
    AccountMetaSpec,
    BookendKind,
    BuildStatus,
    CapacityStatus,
    ConformanceErrorCode,
    SequenceItem,
    UnsignedBorrowPlan,
    UnsignedBuilderError,
    UnsignedSolanaBookend,
    finalize_unsigned_solana_plan,
)
from src.lending.unsigned_builders.kamino_builder import (
    KAMINO_BUILDER_SOURCE_PIN,
    KAMINO_FLASH_BORROW_ABI_PINNED,
    KAMINO_FLASH_BORROW_DISCRIMINATOR_HEX,
    KAMINO_FLASH_REPAY_ABI_PINNED,
    KAMINO_FLASH_REPAY_DISCRIMINATOR_HEX,
    KAMINO_KLEND_PROGRAM_ID,
    KAMINO_MAX_F,
    KAMINO_ONE_SF,
    KaminoFeeProjection,
    KaminoFlashAccounts,
    assemble_kamino_flash_message,
    build_kamino_flash_borrow_bookend,
    build_kamino_flash_borrow_plan,
    build_kamino_flash_repay_bookend,
    build_kamino_flash_repay_plan,
    compute_flash_loan_repayment,
    decode_reserve_fees,
    encode_kamino_flash_borrow_data,
    encode_kamino_flash_repay_data,
    resolve_absolute_borrow_index,
    retarget_borrow_index,
)
from tests.r03_support import SYNTHETIC, kamino_flash_accounts, load_fixture

pytestmark = pytest.mark.unit

KLEND_PROGRAM = "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD"
COMPUTE_BUDGET_PROGRAM = "11111111111111111111111111111111"


def test_golden_reserve_fees_decode() -> None:
    fixture = load_fixture("kamino_golden.json")
    payload = bytes.fromhex(fixture["reserve_fees_borsh_payload_hex"])
    origination_fee_sf, flash_loan_fee_sf = decode_reserve_fees(payload)
    assert origination_fee_sf == fixture["expected_origination_fee_sf"]
    assert flash_loan_fee_sf == fixture["expected_flash_loan_fee_sf"]


def test_golden_fee_vectors_match_pinned_fraction_semantics() -> None:
    fixture = load_fixture("kamino_golden.json")
    for vector in fixture["fee_vectors"]:
        projection = compute_flash_loan_repayment(vector["principal"], vector["fee_sf"])
        assert projection.fee_floor == vector["fee_floor"]
        assert projection.fee_ceil == vector["fee_ceil"]
        assert projection.floor_required_repayment == vector["floor_required_repayment"]
        assert (
            projection.conservative_required_repayment
            == vector["conservative_required_repayment"]
        )
        assert projection.onchain_rounding_known == vector["onchain_rounding_known"]
        assert projection.onchain_rounding_known is False


def test_nonzero_fee_is_respected_and_never_understated() -> None:
    projection = compute_flash_loan_repayment(1_000_000, 300_000)
    assert projection.fee_floor == 0  # floor(1e6 * 3e5 / 2^60) == 0
    assert projection.fee_ceil == 1
    assert projection.conservative_required_repayment == 1_000_001
    assert (
        projection.conservative_required_repayment
        >= projection.floor_required_repayment
    )


def test_zero_fee_sf_is_a_pinned_value_not_an_unknown() -> None:
    projection = compute_flash_loan_repayment(1_000_000, 0)
    assert projection.fee_floor == 0 and projection.fee_ceil == 0
    assert projection.conservative_required_repayment == 1_000_000
    assert projection.onchain_rounding_known is False


def test_unknown_fee_never_defaults_to_zero() -> None:
    with pytest.raises(UnsignedBuilderError) as excinfo:
        compute_flash_loan_repayment(1_000_000, None)
    assert excinfo.value.violations[0].code is ConformanceErrorCode.INVALID_INPUT
    assert "refusing to assume zero" in excinfo.value.violations[0].message


def test_fee_sf_out_of_pinned_fraction_range_rejected() -> None:
    with pytest.raises(UnsignedBuilderError):
        compute_flash_loan_repayment(1_000_000, KAMINO_MAX_F + 1)
    with pytest.raises(UnsignedBuilderError):
        compute_flash_loan_repayment(1_000_000, -1)
    with pytest.raises(UnsignedBuilderError):
        compute_flash_loan_repayment(0, 0)


def test_golden_borrow_index_and_retarget_vectors() -> None:
    fixture = load_fixture("kamino_golden.json")
    vector = fixture["borrow_index_vector"]
    sequence = [
        SequenceItem(program_id=item["program_id"], data_hex=item["data_hex"])
        for item in vector["sequence"]
    ]
    borrow_instruction = sequence[vector["borrow_position_in_sequence"]]
    index = resolve_absolute_borrow_index(
        sequence, borrow_instruction, repay_index=vector["repay_index_supplied"]
    )
    assert index == vector["expected_absolute_borrow_index"]
    retarget = fixture["retarget_vector"]
    assert (
        retarget_borrow_index(retarget["original_index"], retarget["inserted_before"])
        == retarget["expected"]
    )


def test_borrow_index_retargets_after_compute_budget_and_route_insertion() -> None:
    program = SYNTHETIC["generic_route"]
    borrow = SequenceItem(program_id=KLEND_PROGRAM, data_hex="aabbccdd01")
    base = [borrow, SequenceItem(program_id=program, data_hex="aa")]
    assert resolve_absolute_borrow_index(base, borrow, repay_index=2) == 0
    expanded = [
        SequenceItem(program_id=COMPUTE_BUDGET_PROGRAM, data_hex="00"),
        SequenceItem(program_id=COMPUTE_BUDGET_PROGRAM, data_hex="01"),
        borrow,
        SequenceItem(program_id=program, data_hex="aa"),
    ]
    assert resolve_absolute_borrow_index(expanded, borrow, repay_index=4) == 2


def test_borrow_index_missing_duplicate_overflow_and_order() -> None:
    borrow = SequenceItem(program_id=KLEND_PROGRAM, data_hex="aabbccdd01")
    other = SequenceItem(program_id=KLEND_PROGRAM, data_hex="ee")
    with pytest.raises(UnsignedBuilderError) as excinfo:
        resolve_absolute_borrow_index([other], borrow)
    assert excinfo.value.violations[0].code is ConformanceErrorCode.BOOKEND_MISSING
    with pytest.raises(UnsignedBuilderError) as excinfo:
        resolve_absolute_borrow_index([borrow, borrow], borrow)
    assert excinfo.value.violations[0].code is ConformanceErrorCode.DUPLICATE_BOOKEND
    long_sequence = [
        SequenceItem(program_id=COMPUTE_BUDGET_PROGRAM, data_hex="00")
        for _ in range(256)
    ] + [borrow]
    with pytest.raises(UnsignedBuilderError) as excinfo:
        resolve_absolute_borrow_index(long_sequence, borrow)
    assert excinfo.value.violations[0].code is ConformanceErrorCode.REPAY_INDEX_OVERFLOW
    with pytest.raises(UnsignedBuilderError) as excinfo:
        resolve_absolute_borrow_index([borrow], borrow, repay_index=0)
    assert (
        excinfo.value.violations[0].code is ConformanceErrorCode.BOOKEND_ORDER_INVALID
    )


def test_retarget_overflow_fails_closed() -> None:
    assert retarget_borrow_index(255, 0) == 255
    with pytest.raises(UnsignedBuilderError) as excinfo:
        retarget_borrow_index(255, 1)
    assert excinfo.value.violations[0].code is ConformanceErrorCode.REPAY_INDEX_OVERFLOW
    with pytest.raises(UnsignedBuilderError):
        retarget_borrow_index(-1, 0)


def test_golden_flash_borrow_instruction_bytes() -> None:
    """Deterministic golden bytes for the pinned flashBorrowReserveLiquidity ABI."""

    fixture = load_fixture("kamino_flash_abi_golden.json")
    accounts = kamino_flash_accounts()
    bookend = build_kamino_flash_borrow_bookend(accounts, fixture["liquidity_amount"])
    assert bookend.program_id == KAMINO_KLEND_PROGRAM_ID
    assert bookend.discriminator_hex == fixture["borrow_discriminator_hex"]
    assert bookend.data_hex == fixture["borrow_data_hex"]
    assert bookend.data_hex.startswith(KAMINO_FLASH_BORROW_DISCRIMINATOR_HEX)
    assert bookend.amount_base_units == fixture["liquidity_amount"]
    assert len(bookend.account_metas) == 12
    for meta, expected in zip(bookend.account_metas, fixture["expected_metas"]):
        assert meta.pubkey == expected["pubkey"]
        assert meta.is_signer == expected["is_signer"]
        assert meta.is_writable == expected["is_writable"]
    # Pinned codegen: data = discriminator(8) + borsh u64 LE.
    assert bytes.fromhex(bookend.data_hex) == encode_kamino_flash_borrow_data(
        fixture["liquidity_amount"]
    )


def test_golden_flash_repay_instruction_bytes() -> None:
    """Deterministic golden bytes for the pinned flashRepayReserveLiquidity ABI."""

    fixture = load_fixture("kamino_flash_abi_golden.json")
    accounts = kamino_flash_accounts()
    borrow_bookend = build_kamino_flash_borrow_bookend(
        accounts, fixture["liquidity_amount"]
    )
    repay_bookend = build_kamino_flash_repay_bookend(
        accounts,
        fixture["liquidity_amount"],
        fixture["repay_borrow_instruction_index"],
    )
    assert repay_bookend.program_id == KAMINO_KLEND_PROGRAM_ID
    assert repay_bookend.discriminator_hex == fixture["repay_discriminator_hex"]
    assert repay_bookend.data_hex == fixture["repay_data_hex"]
    assert repay_bookend.data_hex.startswith(KAMINO_FLASH_REPAY_DISCRIMINATOR_HEX)
    assert len(repay_bookend.account_metas) == 12
    # Flash bracket: borrow and repay bind the exact same ordered metas.
    assert repay_bookend.meta_fingerprint == borrow_bookend.meta_fingerprint
    # u8 borrowInstructionIndex is the final data byte.
    assert bytes.fromhex(repay_bookend.data_hex)[-1] == 2
    assert bytes.fromhex(repay_bookend.data_hex) == encode_kamino_flash_repay_data(
        fixture["liquidity_amount"], fixture["repay_borrow_instruction_index"]
    )


def test_referrer_some_branch_matches_pinned_codegen() -> None:
    fixture = load_fixture("kamino_flash_abi_golden.json")
    accounts = KaminoFlashAccounts(
        **{
            **fixture["accounts"],
            "referrer_token_state": SYNTHETIC["generic_a"],
            "referrer_account": SYNTHETIC["generic_b"],
        }
    )
    metas = accounts.ordered_metas()
    assert len(metas) == 12
    # Some branch: supplied pubkey, writable (role 1), slots 9 and 10.
    assert metas[8] == AccountMetaSpec(
        pubkey=SYNTHETIC["generic_a"], is_signer=False, is_writable=True
    )
    assert metas[9] == AccountMetaSpec(
        pubkey=SYNTHETIC["generic_b"], is_signer=False, is_writable=True
    )
    # None branch stays on the program address, readonly (pinned default).
    assert metas[10].pubkey == fixture["accounts"]["instructions_sysvar"]
    assert metas[11].pubkey == fixture["accounts"]["token_program"]


def test_golden_flash_plans_are_built_offline_unqualified() -> None:
    fixture = load_fixture("kamino_flash_abi_golden.json")
    accounts = kamino_flash_accounts()
    borrow = build_kamino_flash_borrow_plan(
        principal_base_units=fixture["liquidity_amount"],
        flash_loan_fee_sf=fixture["flash_loan_fee_sf"],
        state_fingerprint="ab" * 32,
        destination_token_account_confirmed=True,
        accounts=accounts,
    )
    assert borrow.build_status is BuildStatus.BUILT_OFFLINE_UNQUALIFIED
    assert borrow.capacity_status is CapacityStatus.NOT_EVALUATED
    assert borrow.blockers == ()
    assert borrow.bookend is not None
    assert borrow.bookend.data_hex == fixture["borrow_data_hex"]
    assert (
        borrow.required_repayment_base_units
        == fixture["expected_required_repayment_base_units"]
    )
    repay = build_kamino_flash_repay_plan(
        borrow_plan=borrow,
        flash_loan_fee_sf=fixture["flash_loan_fee_sf"],
        state_fingerprint="ab" * 32,
        destination_token_account_confirmed=True,
        accounts=accounts,
        borrow_instruction_index=fixture["repay_borrow_instruction_index"],
    )
    assert repay.build_status is BuildStatus.BUILT_OFFLINE_UNQUALIFIED
    assert repay.capacity_status is CapacityStatus.NOT_EVALUATED
    assert repay.blockers == ()
    assert repay.bookend is not None
    assert repay.borrow_bookend is borrow.bookend
    assert repay.bookend.data_hex == fixture["repay_data_hex"]
    assert repay.borrow_index_u8_required is True
    assert (
        repay.required_repayment_base_units
        == fixture["expected_required_repayment_base_units"]
    )
    # Build fingerprints are deterministic for an identical binding.
    assert (
        borrow.build_fingerprint
        == build_kamino_flash_borrow_plan(
            principal_base_units=fixture["liquidity_amount"],
            flash_loan_fee_sf=fixture["flash_loan_fee_sf"],
            state_fingerprint="ab" * 32,
            destination_token_account_confirmed=True,
            accounts=kamino_flash_accounts(),
        ).build_fingerprint
    )


def test_assemble_kamino_flash_message_golden_sequence() -> None:
    fixture = load_fixture("kamino_flash_abi_golden.json")
    accounts = kamino_flash_accounts()
    borrow = build_kamino_flash_borrow_plan(
        principal_base_units=fixture["liquidity_amount"],
        flash_loan_fee_sf=fixture["flash_loan_fee_sf"],
        state_fingerprint="ab" * 32,
        destination_token_account_confirmed=True,
        accounts=accounts,
    )
    # Final ordering: 2 compute-budget instructions -> borrow -> route -> repay.
    repay = build_kamino_flash_repay_plan(
        borrow_plan=borrow,
        flash_loan_fee_sf=fixture["flash_loan_fee_sf"],
        state_fingerprint="ab" * 32,
        destination_token_account_confirmed=True,
        accounts=accounts,
        borrow_instruction_index=2,
    )
    finalized = assemble_kamino_flash_message(
        borrow_plan=borrow,
        repay_plan=repay,
        before_borrow=[
            SequenceItem(
                program_id=COMPUTE_BUDGET_PROGRAM, data_hex="25fd030000000000"
            ),
            SequenceItem(program_id=COMPUTE_BUDGET_PROGRAM, data_hex="02"),
        ],
        route_between=[
            SequenceItem(program_id=SYNTHETIC["generic_route"], data_hex="cafe")
        ],
        after_repay=[],
    )
    assert finalized.certificate.borrow_index == 2
    assert finalized.certificate.repay_index == 4
    assert finalized.certificate.intervening_instruction_count == 1
    assert finalized.provider == "kamino"
    assert finalized.program_id == KAMINO_KLEND_PROGRAM_ID
    assert finalized.sequence[2].data_hex == fixture["borrow_data_hex"]
    assert finalized.sequence[4].data_hex == fixture["repay_data_hex"]
    assert finalized.sequence_fingerprint == finalized.sequence_fingerprint


def test_repay_index_shift_without_rebuild_fails_closed() -> None:
    """Route/compute-budget insertion shifts the borrow index; a stale repay
    reference is a typed conformance failure, never silently accepted."""

    fixture = load_fixture("kamino_flash_abi_golden.json")
    accounts = kamino_flash_accounts()
    borrow = build_kamino_flash_borrow_plan(
        principal_base_units=fixture["liquidity_amount"],
        flash_loan_fee_sf=0,
        state_fingerprint="ab" * 32,
        destination_token_account_confirmed=True,
        accounts=accounts,
    )
    stale = build_kamino_flash_repay_plan(
        borrow_plan=borrow,
        flash_loan_fee_sf=0,
        state_fingerprint="ab" * 32,
        destination_token_account_confirmed=True,
        accounts=accounts,
        borrow_instruction_index=0,
    )
    retargeted = build_kamino_flash_repay_plan(
        borrow_plan=borrow,
        flash_loan_fee_sf=0,
        state_fingerprint="ab" * 32,
        destination_token_account_confirmed=True,
        accounts=accounts,
        borrow_instruction_index=retarget_borrow_index(0, 2),
    )
    with pytest.raises(UnsignedBuilderError) as excinfo:
        assemble_kamino_flash_message(
            borrow_plan=borrow,
            repay_plan=stale,
            before_borrow=[
                SequenceItem(program_id=COMPUTE_BUDGET_PROGRAM, data_hex="00"),
                SequenceItem(program_id=COMPUTE_BUDGET_PROGRAM, data_hex="01"),
            ],
        )
    assert excinfo.value.violations[0].code is ConformanceErrorCode.INVALID_INPUT
    assert "does not match the final absolute borrow index 2" in (
        excinfo.value.violations[0].message
    )
    # Rebuilt with the retargeted index, the same ordering finalizes.
    finalized = assemble_kamino_flash_message(
        borrow_plan=borrow,
        repay_plan=retargeted,
        before_borrow=[
            SequenceItem(program_id=COMPUTE_BUDGET_PROGRAM, data_hex="00"),
            SequenceItem(program_id=COMPUTE_BUDGET_PROGRAM, data_hex="01"),
        ],
    )
    assert finalized.certificate.borrow_index == 2


def test_duplicated_or_foreign_bookends_fail_closed_in_assembly() -> None:
    """Bracket bookends: produced once, consumed exactly once, right program."""

    fixture = load_fixture("kamino_flash_abi_golden.json")
    accounts = kamino_flash_accounts()
    borrow = build_kamino_flash_borrow_plan(
        principal_base_units=fixture["liquidity_amount"],
        flash_loan_fee_sf=0,
        state_fingerprint="ab" * 32,
        destination_token_account_confirmed=True,
        accounts=accounts,
    )
    repay = build_kamino_flash_repay_plan(
        borrow_plan=borrow,
        flash_loan_fee_sf=0,
        state_fingerprint="ab" * 32,
        destination_token_account_confirmed=True,
        accounts=accounts,
        borrow_instruction_index=0,
    )
    stale_borrow_item = borrow.bookend.to_sequence_item()
    route = SequenceItem(program_id=SYNTHETIC["generic_route"], data_hex="cafe")
    # Duplicated borrow bookend: the repay index reference would be ambiguous
    # -> the frozen contract refuses the ordering.
    with pytest.raises(UnsignedBuilderError) as excinfo:
        assemble_kamino_flash_message(
            borrow_plan=borrow,
            repay_plan=repay,
            route_between=[route, stale_borrow_item],
        )
    assert excinfo.value.violations[0].code is ConformanceErrorCode.BOOKEND_MISSING
    assert "found 2 borrow" in excinfo.value.violations[0].message
    # A repay-discriminator-shaped instruction under a foreign program is a
    # hard PROGRAM_ID_MISMATCH, never a silently swapped bookend.
    with pytest.raises(UnsignedBuilderError) as excinfo:
        assemble_kamino_flash_message(
            borrow_plan=borrow,
            repay_plan=repay,
            after_repay=[
                SequenceItem(
                    program_id=SYNTHETIC["generic_route"],
                    data_hex=KAMINO_FLASH_REPAY_DISCRIMINATOR_HEX + "ff",
                )
            ],
        )
    assert excinfo.value.violations[0].code is ConformanceErrorCode.PROGRAM_ID_MISMATCH
    # Dropped repay bookend: finalization without the repay bookend is refused.
    with pytest.raises(UnsignedBuilderError) as excinfo:
        finalize_unsigned_solana_plan(
            provider="kamino",
            program_id=KAMINO_KLEND_PROGRAM_ID,
            borrow_plan=borrow,
            repay_plan=repay,
            sequence=[stale_borrow_item],
            borrow_discriminator_hex=KAMINO_FLASH_BORROW_DISCRIMINATOR_HEX,
            repay_discriminator_hex=KAMINO_FLASH_REPAY_DISCRIMINATOR_HEX,
        )
    assert excinfo.value.violations[0].code is ConformanceErrorCode.BOOKEND_MISSING


def test_divergent_repay_binding_fails_closed_on_account_order() -> None:
    """The repay must reuse the borrow's supply vault and user liquidity
    account; a different binding is a typed ACCOUNT_ORDER_MISMATCH."""

    fixture = load_fixture("kamino_flash_abi_golden.json")
    accounts = kamino_flash_accounts()
    borrow = build_kamino_flash_borrow_plan(
        principal_base_units=fixture["liquidity_amount"],
        flash_loan_fee_sf=0,
        state_fingerprint="ab" * 32,
        destination_token_account_confirmed=True,
        accounts=accounts,
    )
    divergent = KaminoFlashAccounts(
        **{
            **fixture["accounts"],
            "user_liquidity_account": SYNTHETIC["borrow_ata"],
        }
    )
    with pytest.raises(UnsignedBuilderError) as excinfo:
        build_kamino_flash_repay_plan(
            borrow_plan=borrow,
            flash_loan_fee_sf=0,
            state_fingerprint="ab" * 32,
            destination_token_account_confirmed=True,
            accounts=divergent,
            borrow_instruction_index=0,
        )
    assert (
        excinfo.value.violations[0].code is ConformanceErrorCode.ACCOUNT_ORDER_MISMATCH
    )


def test_invalid_pubkeys_fail_closed() -> None:
    fixture = load_fixture("kamino_flash_abi_golden.json")
    for broken in ("", "not-a-pubkey", "0" * 63):
        with pytest.raises(UnsignedBuilderError):
            build_kamino_flash_borrow_bookend(
                KaminoFlashAccounts(**{**fixture["accounts"], "reserve": broken}),
                1_000_000,
            )


def test_amount_overflow_and_non_positive_fail_closed() -> None:
    accounts = kamino_flash_accounts()
    with pytest.raises(UnsignedBuilderError) as excinfo:
        build_kamino_flash_borrow_bookend(accounts, 1 << 64)
    assert excinfo.value.violations[0].code is ConformanceErrorCode.INVALID_INPUT
    for bad in (0, -1):
        with pytest.raises(UnsignedBuilderError):
            build_kamino_flash_borrow_bookend(accounts, bad)
        with pytest.raises(UnsignedBuilderError):
            build_kamino_flash_repay_bookend(accounts, bad, 0)
    with pytest.raises(UnsignedBuilderError) as excinfo:
        encode_kamino_flash_repay_data(1, 256)
    assert excinfo.value.violations[0].code is ConformanceErrorCode.REPAY_INDEX_OVERFLOW
    with pytest.raises(UnsignedBuilderError):
        encode_kamino_flash_repay_data(1, -1)
    assert encode_kamino_flash_repay_data(1, 255).hex().endswith("ff")


def test_flash_plans_without_account_binding_are_typed_blocked() -> None:
    """No account binding -> no fabricated instruction bytes (typed blocker)."""

    state_fingerprint = "ab" * 32
    borrow = build_kamino_flash_borrow_plan(
        principal_base_units=1_000_000,
        flash_loan_fee_sf=300_000,
        state_fingerprint=state_fingerprint,
        destination_token_account_confirmed=True,
    )
    assert borrow.build_status is BuildStatus.BLOCKED_INPUT_REQUIRED
    assert borrow.bookend is None
    assert [b.code for b in borrow.blockers] == [
        ConformanceErrorCode.OPERATOR_ACCOUNT_INPUT_REQUIRED
    ]
    assert borrow.capacity_status is CapacityStatus.NOT_EVALUATED
    assert borrow.required_repayment_base_units == 1_000_001
    repay = build_kamino_flash_repay_plan(
        borrow_plan=borrow,
        flash_loan_fee_sf=300_000,
        state_fingerprint=state_fingerprint,
        destination_token_account_confirmed=True,
    )
    assert repay.build_status is BuildStatus.BLOCKED_INPUT_REQUIRED
    assert repay.bookend is None
    assert repay.borrow_bookend is None
    assert repay.borrow_index_u8_required is True
    assert [b.code for b in repay.blockers] == [
        ConformanceErrorCode.OPERATOR_ACCOUNT_INPUT_REQUIRED
    ]


def test_unconfirmed_destination_account_adds_needs_account_setup() -> None:
    without_binding = build_kamino_flash_borrow_plan(
        principal_base_units=1_000_000,
        flash_loan_fee_sf=0,
        state_fingerprint="ab" * 32,
        destination_token_account_confirmed=False,
    )
    assert [b.code for b in without_binding.blockers] == [
        ConformanceErrorCode.OPERATOR_ACCOUNT_INPUT_REQUIRED,
        ConformanceErrorCode.NEEDS_ACCOUNT_SETUP,
    ]
    with_binding = build_kamino_flash_borrow_plan(
        principal_base_units=1_000_000,
        flash_loan_fee_sf=0,
        state_fingerprint="ab" * 32,
        destination_token_account_confirmed=False,
        accounts=kamino_flash_accounts(),
    )
    assert [b.code for b in with_binding.blockers] == [
        ConformanceErrorCode.NEEDS_ACCOUNT_SETUP
    ]
    assert with_binding.bookend is None


def test_built_repay_requires_borrow_index_input() -> None:
    fixture = load_fixture("kamino_flash_abi_golden.json")
    accounts = kamino_flash_accounts()
    borrow = build_kamino_flash_borrow_plan(
        principal_base_units=fixture["liquidity_amount"],
        flash_loan_fee_sf=0,
        state_fingerprint="ab" * 32,
        destination_token_account_confirmed=True,
        accounts=accounts,
    )
    repay = build_kamino_flash_repay_plan(
        borrow_plan=borrow,
        flash_loan_fee_sf=0,
        state_fingerprint="ab" * 32,
        destination_token_account_confirmed=True,
        accounts=accounts,
    )
    assert repay.build_status is BuildStatus.BLOCKED_INPUT_REQUIRED
    assert repay.bookend is None
    assert [b.code for b in repay.blockers] == [ConformanceErrorCode.INVALID_INPUT]
    assert "refusing to assume a value" in repay.blockers[0].message


def test_repay_plan_rejects_a_built_borrow_plan() -> None:
    fabricated = UnsignedBorrowPlan(
        provider="kamino",
        chain="solana",
        source_pin=KAMINO_BUILDER_SOURCE_PIN,
        asset_id="klend:x",
        principal_base_units=1_000,
        bookend=UnsignedSolanaBookend(
            kind=BookendKind.BORROW,
            program_id=KLEND_PROGRAM,
            discriminator_hex="ab" * 8,
            data_hex="ab" * 8 + "01",
            account_metas=(
                AccountMetaSpec(
                    pubkey=SYNTHETIC["signer"], is_signer=True, is_writable=True
                ),
            ),
            amount_base_units=1,
        ),
        state_fingerprint="ab" * 32,
        build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
    )
    with pytest.raises(UnsignedBuilderError) as excinfo:
        build_kamino_flash_repay_plan(
            borrow_plan=fabricated,
            flash_loan_fee_sf=0,
            state_fingerprint="ab" * 32,
            destination_token_account_confirmed=True,
        )
    assert (
        excinfo.value.violations[0].code
        is ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE
    )


def test_kamino_builder_source_pin_matches_pinned_kit() -> None:
    fixture = load_fixture("kamino_golden.json")
    abi_fixture = load_fixture("kamino_flash_abi_golden.json")
    assert KAMINO_BUILDER_SOURCE_PIN.verified_offline is True
    assert KAMINO_BUILDER_SOURCE_PIN.commit == fixture["source_pin"]["commit"]
    assert KAMINO_BUILDER_SOURCE_PIN.version == fixture["source_pin"]["sdk_version"]
    assert KAMINO_BUILDER_SOURCE_PIN.commit == abi_fixture["source_pin"]["commit"]
    assert KAMINO_BUILDER_SOURCE_PIN.version == abi_fixture["source_pin"]["sdk_version"]
    assert len(KAMINO_BUILDER_SOURCE_PIN.source_paths) == 5
    assert len(KAMINO_BUILDER_SOURCE_PIN.blob_sha1s) == 5
    assert abi_fixture["source_pin"]["flash_borrow_blob_sha1"] in (
        KAMINO_BUILDER_SOURCE_PIN.blob_sha1s
    )
    assert abi_fixture["source_pin"]["flash_repay_blob_sha1"] in (
        KAMINO_BUILDER_SOURCE_PIN.blob_sha1s
    )
    assert KAMINO_FLASH_BORROW_ABI_PINNED is True
    assert KAMINO_FLASH_REPAY_ABI_PINNED is True
    assert KAMINO_ONE_SF == 1 << 60
