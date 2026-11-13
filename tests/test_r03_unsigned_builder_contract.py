"""R03-00 frozen unsigned-builder conformance contract tests (offline)."""

from __future__ import annotations

import pytest

from src.lending.unsigned_builders.contract import (
    RECEIPT_TYPE_UNKNOWN,
    CapacityStatus,
    BuildStatus,
    BuilderSourcePin,
    ConformanceErrorCode,
    ConformanceViolation,
    HotPotatoReceipt,
    PtArgument,
    PtBuildResult,
    PtCommand,
    SequenceItem,
    UnsignedBorrowPlan,
    UnsignedRepayPlan,
    UnsignedSolanaBookend,
    UnsignedBuilderError,
    assert_no_execution_ready_capacity_member,
    canonical_hash,
    check_account_order,
    check_bookend_sequence,
    check_hot_potato_receipt,
    check_ptb_package,
    finalize_unsigned_solana_plan,
    AccountMetaSpec,
    BookendKind,
)

pytestmark = pytest.mark.unit


def _pin(verified: bool = True) -> BuilderSourcePin:
    return BuilderSourcePin(
        provider="test",
        chain="solana",
        repository="https://example.com/test",
        commit="a" * 40,
        version="1.0.0",
        license_label="MIT",
        source_paths=("src/example.ts",),
        blob_sha1s=("b" * 40,),
        verified_offline=verified,
    )


def _bookend(
    kind: BookendKind, disc_hex: str, amount: int = 100
) -> UnsignedSolanaBookend:
    return UnsignedSolanaBookend(
        kind=kind,
        program_id="jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS",
        discriminator_hex=disc_hex,
        data_hex=disc_hex + amount.to_bytes(8, "little").hex(),
        account_metas=(
            AccountMetaSpec(
                pubkey="6QWeT6FpJrm8AF1btu6WH2k2Xhq6t5vbheKVfQavmenB",
                is_signer=True,
                is_writable=True,
            ),
            AccountMetaSpec(
                pubkey="6URwbPipuA4MJLG7LCRRZuWnms3JZ9cRG3z9indXWz6t",
                is_signer=False,
                is_writable=True,
            ),
        ),
        amount_base_units=amount,
    )


def _built_borrow_plan(pin: BuilderSourcePin | None = None) -> UnsignedBorrowPlan:
    bookend = _bookend(BookendKind.BORROW, "aa" * 8)
    return UnsignedBorrowPlan(
        provider="test",
        chain="solana",
        source_pin=pin or _pin(),
        asset_id="spl:fixture:6",
        principal_base_units=100,
        bookend=bookend,
        required_repayment_base_units=None,
        state_fingerprint="c" * 64,
        build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
    )


def test_capacity_status_has_no_execution_ready_member() -> None:
    assert_no_execution_ready_capacity_member()
    assert "EXECUTION_READY" not in CapacityStatus.__members__
    assert set(CapacityStatus.__members__) == {
        "NOT_EVALUATED",
        "PENDING_R02_CAPACITY_GATE",
        "CAPACITY_UNQUALIFIED",
    }


def test_built_plan_requires_bookend_and_forbids_blockers() -> None:
    with pytest.raises(UnsignedBuilderError) as excinfo:
        UnsignedBorrowPlan(
            provider="test",
            chain="solana",
            source_pin=_pin(),
            asset_id="x",
            principal_base_units=1,
            bookend=None,
            build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
        )
    assert (
        excinfo.value.violations[0].code
        is ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE
    )
    with pytest.raises(UnsignedBuilderError) as excinfo:
        UnsignedBorrowPlan(
            provider="test",
            chain="solana",
            source_pin=_pin(),
            asset_id="x",
            principal_base_units=1,
            bookend=_bookend(BookendKind.BORROW, "aa" * 8),
            blockers=(
                ConformanceViolation(
                    code=ConformanceErrorCode.INVALID_INPUT,
                    message="x",
                    provider="test",
                ),
            ),
            build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
        )
    assert (
        excinfo.value.violations[0].code
        is ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE
    )


def test_blocked_plan_requires_typed_blocker_and_forbids_bookend() -> None:
    with pytest.raises(UnsignedBuilderError) as excinfo:
        UnsignedBorrowPlan(
            provider="test",
            chain="solana",
            source_pin=_pin(),
            asset_id="x",
            principal_base_units=1,
            bookend=None,
            blockers=(),
            build_status=BuildStatus.BLOCKED_INPUT_REQUIRED,
        )
    assert excinfo.value.violations[0].code is ConformanceErrorCode.INVALID_INPUT
    with pytest.raises(UnsignedBuilderError) as excinfo:
        UnsignedBorrowPlan(
            provider="test",
            chain="solana",
            source_pin=_pin(),
            asset_id="x",
            principal_base_units=1,
            bookend=_bookend(BookendKind.BORROW, "aa" * 8),
            blockers=(
                ConformanceViolation(
                    code=ConformanceErrorCode.NEEDS_ACCOUNT_SETUP,
                    message="x",
                    provider="test",
                ),
            ),
            build_status=BuildStatus.BLOCKED_INPUT_REQUIRED,
        )
    assert (
        excinfo.value.violations[0].code
        is ConformanceErrorCode.BUILD_CAPACITY_ADMIXTURE
    )


def test_zero_repayment_forbidden_unknown_recorded_as_none() -> None:
    with pytest.raises(UnsignedBuilderError) as excinfo:
        UnsignedBorrowPlan(
            provider="test",
            chain="solana",
            source_pin=_pin(),
            asset_id="x",
            principal_base_units=100,
            bookend=None,
            required_repayment_base_units=0,
            blockers=(
                ConformanceViolation(
                    code=ConformanceErrorCode.INVALID_INPUT,
                    message="x",
                    provider="test",
                ),
            ),
            build_status=BuildStatus.BLOCKED_INPUT_REQUIRED,
        )
    assert (
        excinfo.value.violations[0].code
        is ConformanceErrorCode.REPAYMENT_BELOW_PRINCIPAL
    )
    plan = _built_borrow_plan()
    assert plan.required_repayment_base_units is None


def test_repayment_below_principal_rejected() -> None:
    with pytest.raises(UnsignedBuilderError) as excinfo:
        UnsignedBorrowPlan(
            provider="test",
            chain="solana",
            source_pin=_pin(),
            asset_id="x",
            principal_base_units=100,
            bookend=_bookend(BookendKind.BORROW, "aa" * 8),
            required_repayment_base_units=99,
            state_fingerprint="c" * 64,
            build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
        )
    assert (
        excinfo.value.violations[0].code
        is ConformanceErrorCode.REPAYMENT_BELOW_PRINCIPAL
    )


def test_source_pin_unverified_fails_closed() -> None:
    with pytest.raises(UnsignedBuilderError) as excinfo:
        _pin(verified=False).require_verified()
    assert (
        excinfo.value.violations[0].code is ConformanceErrorCode.SOURCE_PIN_UNVERIFIED
    )
    with pytest.raises(UnsignedBuilderError):
        BuilderSourcePin(
            provider="test",
            chain="solana",
            repository="r",
            commit="short",
            version="1",
            license_label="MIT",
            source_paths=("p",),
            verified_offline=True,
        )


def test_bookend_sequence_missing_and_duplicate() -> None:
    borrow_hex = "aa" * 8
    repay_hex = "bb" * 8
    sequence = [
        SequenceItem(
            program_id="jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS",
            data_hex=borrow_hex + "64",
        ),
        SequenceItem(
            program_id="jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS",
            data_hex=borrow_hex + "c8",
        ),
        SequenceItem(
            program_id="jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS",
            data_hex=repay_hex + "64",
        ),
    ]
    with pytest.raises(UnsignedBuilderError) as excinfo:
        check_bookend_sequence(
            provider="test",
            program_id="jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS",
            sequence=sequence,
            borrow_discriminator_hex=borrow_hex,
            repay_discriminator_hex=repay_hex,
        )
    assert excinfo.value.violations[0].code is ConformanceErrorCode.BOOKEND_MISSING
    with pytest.raises(UnsignedBuilderError):
        check_bookend_sequence(
            provider="test",
            program_id="jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS",
            sequence=sequence + sequence,
            borrow_discriminator_hex=borrow_hex,
            repay_discriminator_hex=repay_hex,
        )


def test_bookend_order_invalid_and_program_mismatch() -> None:
    borrow_hex = "aa" * 8
    repay_hex = "bb" * 8
    program = "jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS"
    borrow_item = SequenceItem(program_id=program, data_hex=borrow_hex + "64")
    repay_item = SequenceItem(program_id=program, data_hex=repay_hex + "64")
    with pytest.raises(UnsignedBuilderError) as excinfo:
        check_bookend_sequence(
            provider="test",
            program_id=program,
            sequence=[repay_item, borrow_item],
            borrow_discriminator_hex=borrow_hex,
            repay_discriminator_hex=repay_hex,
        )
    assert (
        excinfo.value.violations[0].code is ConformanceErrorCode.BOOKEND_ORDER_INVALID
    )
    impostor = SequenceItem(
        program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        data_hex=borrow_hex + "64",
    )
    with pytest.raises(UnsignedBuilderError) as excinfo:
        check_bookend_sequence(
            provider="test",
            program_id=program,
            sequence=[impostor, repay_item],
            borrow_discriminator_hex=borrow_hex,
            repay_discriminator_hex=repay_hex,
        )
    assert excinfo.value.violations[0].code is ConformanceErrorCode.PROGRAM_ID_MISMATCH


def test_account_order_mismatch() -> None:
    borrow = _bookend(BookendKind.BORROW, "aa" * 8)
    repay = UnsignedSolanaBookend(
        kind=BookendKind.REPAY,
        program_id=borrow.program_id,
        discriminator_hex="bb" * 8,
        data_hex="bb" * 8 + "64",
        account_metas=(
            AccountMetaSpec(
                pubkey="6URwbPipuA4MJLG7LCRRZuWnms3JZ9cRG3z9indXWz6t",
                is_signer=True,
                is_writable=True,
            ),
            AccountMetaSpec(
                pubkey="6QWeT6FpJrm8AF1btu6WH2k2Xhq6t5vbheKVfQavmenB",
                is_signer=False,
                is_writable=True,
            ),
        ),
        amount_base_units=100,
    )
    with pytest.raises(UnsignedBuilderError) as excinfo:
        check_account_order(provider="test", borrow_bookend=borrow, repay_bookend=repay)
    assert (
        excinfo.value.violations[0].code is ConformanceErrorCode.ACCOUNT_ORDER_MISMATCH
    )


def test_hot_potato_lifecycle_failures() -> None:
    package = "0x" + "ab" * 32
    borrow = PtCommand(
        name="borrow",
        target=f"{package}::lending::flash_loan_with_ctx",
        type_arguments=("0x2::sui::SUI",),
        arguments=(PtArgument(kind="object_id", value="0x" + "cd" * 32),),
        result_names=("balance", "receipt"),
    )
    repay = PtCommand(
        name="repay",
        target=f"{package}::lending::flash_repay_with_ctx",
        type_arguments=("0x2::sui::SUI",),
        arguments=(PtArgument(kind="result_ref", value="result:0:1"),),
        result_names=("repaid",),
    )
    receipt = HotPotatoReceipt(
        result_ref="result:0:1", producer_command_index=0, consumed_by_command_index=1
    )
    check_hot_potato_receipt((borrow, repay), receipt)
    with pytest.raises(UnsignedBuilderError) as excinfo:
        check_hot_potato_receipt((borrow,), receipt)
    assert (
        excinfo.value.violations[0].code is ConformanceErrorCode.HOT_POTATO_UNCONSUMED
    )
    duplicate = PtCommand(
        name="repay_again",
        target=f"{package}::lending::flash_repay_with_ctx",
        type_arguments=("0x2::sui::SUI",),
        arguments=(PtArgument(kind="result_ref", value="result:0:1"),),
        result_names=("repaid2",),
    )
    with pytest.raises(UnsignedBuilderError) as excinfo:
        check_hot_potato_receipt((borrow, repay, duplicate), receipt)
    assert (
        excinfo.value.violations[0].code
        is ConformanceErrorCode.HOT_POTATO_DUPLICATE_DISCHARGE
    )
    with pytest.raises(UnsignedBuilderError) as excinfo:
        check_hot_potato_receipt((repay, borrow), receipt)
    assert (
        excinfo.value.violations[0].code
        is ConformanceErrorCode.HOT_POTATO_ORDER_INVALID
    )


def test_check_ptb_package_mismatch() -> None:
    package = "0x" + "ab" * 32
    other = "0x" + "ff" * 32
    command = PtCommand(
        name="x",
        target=f"{other}::lending::flash_loan_with_ctx",
        type_arguments=("0x2::sui::SUI",),
        arguments=(),
        result_names=("r",),
    )
    with pytest.raises(UnsignedBuilderError) as excinfo:
        check_ptb_package((command,), package)
    assert excinfo.value.violations[0].code is ConformanceErrorCode.PACKAGE_ID_MISMATCH


def test_built_ptb_requires_discharged_receipt() -> None:
    package = "0x" + "ab" * 32
    commands = (
        PtCommand(
            name="borrow",
            target=f"{package}::lending::flash_loan_with_ctx",
            type_arguments=("0x2::sui::SUI",),
            arguments=(),
            result_names=("balance", "receipt"),
        ),
    )
    with pytest.raises(UnsignedBuilderError) as excinfo:
        PtBuildResult(
            provider="navi",
            package_id=package,
            config_version=1,
            commands=commands,
            receipt=None,
            source_pin=_pin(),
            build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
        )
    assert (
        excinfo.value.violations[0].code is ConformanceErrorCode.HOT_POTATO_UNCONSUMED
    )
    blocked = PtBuildResult(
        provider="navi",
        package_id=package,
        config_version=None,
        commands=(),
        receipt=None,
        source_pin=_pin(),
        blockers=(
            ConformanceViolation(
                code=ConformanceErrorCode.OPERATOR_ACCOUNT_INPUT_REQUIRED,
                message="x",
                provider="navi",
            ),
        ),
        build_status=BuildStatus.BLOCKED_INPUT_REQUIRED,
    )
    assert blocked.capacity_status is CapacityStatus.NOT_EVALUATED
    assert blocked.build_fingerprint


def test_finalize_repay_index_u8_overflow() -> None:
    from src.lending.unsigned_builders.contract import UnsignedBuilderError as err
    from src.lending.unsigned_builders.contract import (
        finalize_unsigned_solana_plan as finalize,
    )

    borrow_hex = "aa" * 8
    repay_hex = "bb" * 8
    program = "jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS"
    borrow_plan = _built_borrow_plan()
    repay_plan = UnsignedRepayPlan(
        provider="test",
        chain="solana",
        source_pin=_pin(),
        asset_id="spl:fixture:6",
        bookend=_bookend(BookendKind.REPAY, repay_hex),
        borrow_bookend=borrow_plan.bookend,
        required_repayment_base_units=100,
        borrow_index_u8_required=True,
        state_fingerprint="c" * 64,
        build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
    )
    sequence = [
        SequenceItem(program_id="11111111111111111111111111111111", data_hex="00")
        for _ in range(300)
    ]
    sequence.insert(300, borrow_plan.bookend.to_sequence_item())
    sequence.append(repay_plan.bookend.to_sequence_item())
    with pytest.raises(err) as excinfo:
        finalize(
            provider="test",
            program_id=program,
            borrow_plan=borrow_plan,
            repay_plan=repay_plan,
            sequence=sequence,
            borrow_discriminator_hex=borrow_hex,
            repay_discriminator_hex=repay_hex,
        )
    assert excinfo.value.violations[0].code is ConformanceErrorCode.REPAY_INDEX_OVERFLOW


def test_finalize_amount_mismatch() -> None:
    borrow_hex = "aa" * 8
    repay_hex = "bb" * 8
    program = "jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS"
    borrow_plan = _built_borrow_plan()
    mismatched_repay = UnsignedSolanaBookend(
        kind=BookendKind.REPAY,
        program_id=program,
        discriminator_hex=repay_hex,
        data_hex=repay_hex + (100).to_bytes(8, "little").hex(),
        account_metas=borrow_plan.bookend.account_metas,
        amount_base_units=999,
    )
    repay_plan = UnsignedRepayPlan(
        provider="test",
        chain="solana",
        source_pin=_pin(),
        asset_id="spl:fixture:6",
        bookend=mismatched_repay,
        borrow_bookend=borrow_plan.bookend,
        required_repayment_base_units=999,
        state_fingerprint="c" * 64,
        build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
    )
    sequence = [
        borrow_plan.bookend.to_sequence_item(),
        repay_plan.bookend.to_sequence_item(),
    ]
    with pytest.raises(UnsignedBuilderError) as excinfo:
        finalize_unsigned_solana_plan(
            provider="test",
            program_id=program,
            borrow_plan=borrow_plan,
            repay_plan=repay_plan,
            sequence=sequence,
            borrow_discriminator_hex=borrow_hex,
            repay_discriminator_hex=repay_hex,
        )
    assert excinfo.value.violations[0].code is ConformanceErrorCode.AMOUNT_MISMATCH


def test_sui_object_id_shorthand_normalization() -> None:
    from src.lending.unsigned_builders.contract import _validate_object_id

    assert _validate_object_id("0x05", "x") == "0x" + "0" * 63 + "5"
    assert _validate_object_id("0x" + "AB" * 32, "x") == "0x" + "ab" * 32
    with pytest.raises(UnsignedBuilderError):
        _validate_object_id("0xzz", "x")


def test_ptb_argument_validation() -> None:
    with pytest.raises(UnsignedBuilderError):
        PtArgument(kind="result_ref", value="result:0")
    with pytest.raises(UnsignedBuilderError) as excinfo:
        PtArgument(kind="pure", value=f"u64:{(1 << 64)}")
    assert excinfo.value.violations[0].code is ConformanceErrorCode.PTB_AMOUNT_INVALID
    with pytest.raises(UnsignedBuilderError):
        PtArgument(kind="warp", value="x")


def test_canonical_hash_is_deterministic_and_order_sensitive() -> None:
    a = SequenceItem(program_id="11111111111111111111111111111111", data_hex="00")
    b = SequenceItem(program_id="11111111111111111111111111111111", data_hex="01")
    assert canonical_hash((a, b)) == canonical_hash((a, b))
    assert canonical_hash((a, b)) != canonical_hash((b, a))


def test_receipt_type_unknown_is_never_guessed() -> None:
    assert RECEIPT_TYPE_UNKNOWN == "UNKNOWN"
    receipt = HotPotatoReceipt(result_ref="result:0:1", producer_command_index=0)
    assert receipt.receipt_type == RECEIPT_TYPE_UNKNOWN
    assert receipt.consumed_by_command_index is None
