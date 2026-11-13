"""R03-B Kamino unsigned builder tests: pinned fee/index semantics + typed ABI block."""

from __future__ import annotations

import pytest

from src.lending.unsigned_builders.contract import (
    BuildStatus,
    CapacityStatus,
    ConformanceErrorCode,
    SequenceItem,
    UnsignedBuilderError,
)
from src.lending.unsigned_builders.kamino_builder import (
    KAMINO_MAX_F,
    KAMINO_ONE_SF,
    KaminoFeeProjection,
    build_kamino_flash_borrow_plan,
    build_kamino_flash_repay_plan,
    compute_flash_loan_repayment,
    decode_reserve_fees,
    resolve_absolute_borrow_index,
    retarget_borrow_index,
)
from tests.r03_support import SYNTHETIC, load_fixture

pytestmark = pytest.mark.unit

KLEND_PROGRAM = "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD"


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
        SequenceItem(program_id="11111111111111111111111111111111", data_hex="00"),
        SequenceItem(program_id="11111111111111111111111111111111", data_hex="01"),
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
        SequenceItem(program_id="11111111111111111111111111111111", data_hex="00")
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


def test_flash_plans_are_typed_blocked_without_fabricated_abi() -> None:
    state_fingerprint = "ab" * 32
    borrow = build_kamino_flash_borrow_plan(
        principal_base_units=1_000_000,
        flash_loan_fee_sf=300_000,
        state_fingerprint=state_fingerprint,
        destination_token_account_confirmed=True,
    )
    assert borrow.build_status is BuildStatus.BLOCKED_MISSING_PINNED_BUILDER_ABI
    assert borrow.bookend is None
    assert [b.code for b in borrow.blockers] == [
        ConformanceErrorCode.MISSING_PINNED_BUILDER_ABI
    ]
    assert borrow.capacity_status is CapacityStatus.NOT_EVALUATED
    assert borrow.required_repayment_base_units == 1_000_001
    repay = build_kamino_flash_repay_plan(
        borrow_plan=borrow,
        flash_loan_fee_sf=300_000,
        state_fingerprint=state_fingerprint,
        destination_token_account_confirmed=True,
    )
    assert repay.build_status is BuildStatus.BLOCKED_MISSING_PINNED_BUILDER_ABI
    assert repay.bookend is None
    assert repay.borrow_bookend is None
    assert repay.borrow_index_u8_required is True
    assert [b.code for b in repay.blockers] == [
        ConformanceErrorCode.MISSING_PINNED_BUILDER_ABI
    ]


def test_unconfirmed_destination_account_adds_needs_account_setup() -> None:
    borrow = build_kamino_flash_borrow_plan(
        principal_base_units=1_000_000,
        flash_loan_fee_sf=0,
        state_fingerprint="ab" * 32,
        destination_token_account_confirmed=False,
    )
    codes = [b.code for b in borrow.blockers]
    assert codes == [
        ConformanceErrorCode.MISSING_PINNED_BUILDER_ABI,
        ConformanceErrorCode.NEEDS_ACCOUNT_SETUP,
    ]


def test_repay_plan_rejects_a_built_borrow_plan() -> None:
    from src.lending.unsigned_builders.contract import (
        AccountMetaSpec,
        BookendKind,
        BuilderSourcePin,
        UnsignedBorrowPlan,
        UnsignedSolanaBookend,
    )
    from src.lending.unsigned_builders.kamino_builder import KAMINO_BUILDER_SOURCE_PIN

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
    from src.lending.unsigned_builders.kamino_builder import KAMINO_BUILDER_SOURCE_PIN

    assert KAMINO_BUILDER_SOURCE_PIN.verified_offline is True
    assert KAMINO_BUILDER_SOURCE_PIN.commit == fixture["source_pin"]["commit"]
    assert KAMINO_BUILDER_SOURCE_PIN.version == fixture["source_pin"]["sdk_version"]
    assert KAMINO_ONE_SF == 1 << 60
