"""R03-C NAVI Sui PTB unsigned builder tests: v1/v2 golden + hot-potato negatives."""

from __future__ import annotations

import pytest

from src.lending.unsigned_builders.contract import (
    RECEIPT_TYPE_UNKNOWN,
    BuildStatus,
    CapacityStatus,
    ConformanceErrorCode,
    HotPotatoReceipt,
    PtArgument,
    PtCommand,
    UnsignedBuilderError,
    check_hot_potato_receipt,
)
from src.lending.unsigned_builders.navi_ptb_builder import (
    NAVI_BORROW_FUNCTION_V1,
    NAVI_BORROW_FUNCTION_V2,
    NAVI_BUILDER_PROVIDER,
    NAVI_BUILDER_SOURCE_PIN,
    NAVI_FORBIDDEN_CALLS,
    NAVI_RECEIPT_TYPE,
    NAVI_REPAY_FUNCTION,
    NaviVerifiedDeploymentConfig,
    SUI_CLOCK_ID,
    SUI_SYSTEM_STATE_ID,
    build_navi_flashloan_ptb,
    build_navi_unconsumed_receipt_probe,
    canonical_ptb_json,
    check_navi_command_shape,
)
from src.multichain.sui import SuiObjectKind
from tests.r03_support import (
    NAVI_COIN_TYPE,
    NAVI_FLASHLOAN_CONFIG,
    NAVI_PACKAGE,
    NAVI_POOL,
    NAVI_REPAY_COIN,
    NAVI_STORAGE,
    navi_frame,
    load_fixture,
)

pytestmark = pytest.mark.unit


def _config(version: int = 2) -> NaviVerifiedDeploymentConfig:
    return NaviVerifiedDeploymentConfig(
        package_id=NAVI_PACKAGE,
        storage_id=NAVI_STORAGE,
        flashloan_config_id=NAVI_FLASHLOAN_CONFIG,
        pool_object_id=NAVI_POOL,
        sui_coin_type=NAVI_COIN_TYPE,
        version=version,
        verified=True,
        config_source="offline fixture (synthetic ids; structure conformance only)",
    )


def _repay_coin() -> PtArgument:
    return PtArgument(kind="object_id", value=NAVI_REPAY_COIN, type_tag=NAVI_COIN_TYPE)


def test_golden_v2_canonical_json_replays_deterministically() -> None:
    fixture = load_fixture("navi_ptb_golden.json")
    build = build_navi_flashloan_ptb(
        config=_config(version=2),
        frame=navi_frame(),
        amount=1_500_000,
        repay_coin=_repay_coin(),
        required_repayment_units=1_500_000,
    )
    assert build.result.build_status is BuildStatus.BUILT_OFFLINE_UNQUALIFIED
    assert build.result.capacity_status is CapacityStatus.NOT_EVALUATED
    assert canonical_ptb_json(build) == fixture["v2"]["expected_canonical_json"]
    assert build.result.commands[0].target == fixture["v2"]["expected_borrow_target"]
    assert build.result.commands[1].target == fixture["v2"]["expected_repay_target"]
    assert (
        build.result.receipt.result_ref == fixture["v2"]["expected_receipt_result_ref"]
    )
    assert (
        build.result.receipt.consumed_by_command_index
        == fixture["v2"]["expected_receipt_consumed_by"]
    )
    assert build.frame_checkpoint == fixture["v2"]["frame_checkpoint"]
    replay = build_navi_flashloan_ptb(
        config=_config(version=2),
        frame=navi_frame(),
        amount=1_500_000,
        repay_coin=_repay_coin(),
        required_repayment_units=1_500_000,
    )
    assert canonical_ptb_json(replay) == canonical_ptb_json(build)


def test_golden_v1_uses_flash_loan_with_ctx_without_system_state() -> None:
    fixture = load_fixture("navi_ptb_golden.json")
    build = build_navi_flashloan_ptb(
        config=_config(version=1),
        frame=navi_frame(),
        amount=250_000,
        repay_coin=_repay_coin(),
    )
    assert canonical_ptb_json(build) == fixture["v1"]["expected_canonical_json"]
    borrow = build.result.commands[0]
    assert borrow.function_name == NAVI_BORROW_FUNCTION_V1
    assert fixture["v2"]["expected_borrow_target"].endswith(NAVI_BORROW_FUNCTION_V2)
    assert len(borrow.arguments) == 3
    assert canonical_ptb_json(build) != fixture["v2"]["expected_canonical_json"]


def test_v2_borrow_carries_sui_system_state_and_exact_objects() -> None:
    build = build_navi_flashloan_ptb(
        config=_config(version=2),
        frame=navi_frame(),
        amount=10,
        repay_coin=_repay_coin(),
    )
    borrow_args = build.result.commands[0].arguments
    assert borrow_args[0].value == NAVI_FLASHLOAN_CONFIG
    assert borrow_args[1].value == NAVI_POOL
    assert borrow_args[2].value == "u64:10"
    assert borrow_args[3].value == "0x" + "0" * 63 + "5"
    repay_args = build.result.commands[1].arguments
    assert repay_args[0].value == "0x" + "0" * 63 + "6"
    assert repay_args[1].value == NAVI_STORAGE
    assert repay_args[2].value == NAVI_POOL
    assert repay_args[3].value == "result:0:1"
    assert repay_args[4].value == NAVI_REPAY_COIN


def test_receipt_type_is_unknown_never_guessed() -> None:
    fixture = load_fixture("navi_ptb_golden.json")
    build = build_navi_flashloan_ptb(
        config=_config(version=2),
        frame=navi_frame(),
        amount=10,
        repay_coin=_repay_coin(),
    )
    assert build.result.receipt.receipt_type == RECEIPT_TYPE_UNKNOWN
    assert NAVI_RECEIPT_TYPE == RECEIPT_TYPE_UNKNOWN
    assert fixture["v1"]["expected_receipt_type"] == RECEIPT_TYPE_UNKNOWN


def test_wrong_package_target_fails_closed() -> None:
    config = _config(version=1)
    other_package = "0x" + "ff" * 32
    command = PtCommand(
        name="borrow",
        target=f"{other_package}::lending::{NAVI_BORROW_FUNCTION_V1}",
        type_arguments=(NAVI_COIN_TYPE,),
        arguments=(),
        result_names=("balance", "receipt"),
    )
    from src.lending.unsigned_builders.contract import check_ptb_package

    with pytest.raises(UnsignedBuilderError) as excinfo:
        check_ptb_package((command,), config.package_id)
    assert excinfo.value.violations[0].code is ConformanceErrorCode.PACKAGE_ID_MISMATCH


def test_v2_borrow_missing_sui_system_state_fails_closed() -> None:
    config = _config(version=2)
    broken_borrow = PtCommand(
        name="borrow",
        target=f"{config.package_id}::lending::{NAVI_BORROW_FUNCTION_V2}",
        type_arguments=(NAVI_COIN_TYPE,),
        arguments=(
            PtArgument(kind="object_id", value=config.flashloan_config_id),
            PtArgument(kind="object_id", value=config.pool_object_id),
            PtArgument(kind="pure", value="u64:10"),
        ),
        result_names=("balance", "receipt"),
    )
    repay = PtCommand(
        name="repay",
        target=f"{config.package_id}::lending::{NAVI_REPAY_FUNCTION}",
        type_arguments=(NAVI_COIN_TYPE,),
        arguments=(
            PtArgument(kind="object_id", value=SUI_CLOCK_ID),
            PtArgument(kind="object_id", value=config.storage_id),
            PtArgument(kind="object_id", value=config.pool_object_id),
            PtArgument(kind="result_ref", value="result:0:1"),
            _repay_coin(),
        ),
        result_names=("repaid",),
    )
    with pytest.raises(UnsignedBuilderError) as excinfo:
        check_navi_command_shape(
            config, (broken_borrow, repay), amount=10, repay_coin=_repay_coin()
        )
    assert (
        excinfo.value.violations[0].code
        is ConformanceErrorCode.PTB_REQUIRED_OBJECT_MISSING
    )


def test_unconsumed_hot_potato_receipt_fails_closed() -> None:
    config = _config(version=2)
    probe = build_navi_unconsumed_receipt_probe(config, navi_frame(), 10, _repay_coin())
    receipt = HotPotatoReceipt(result_ref="result:0:1", producer_command_index=0)
    with pytest.raises(UnsignedBuilderError) as excinfo:
        check_hot_potato_receipt(probe, receipt)
    assert (
        excinfo.value.violations[0].code is ConformanceErrorCode.HOT_POTATO_UNCONSUMED
    )


def test_duplicated_receipt_discharge_fails_closed() -> None:
    config = _config(version=1)
    build = build_navi_flashloan_ptb(
        config=config,
        frame=navi_frame(),
        amount=10,
        repay_coin=_repay_coin(),
    )
    repay = build.result.commands[1]
    duplicate = PtCommand(
        name="repay_again",
        target=repay.target,
        type_arguments=repay.type_arguments,
        arguments=repay.arguments,
        result_names=("repaid2",),
    )
    receipt = HotPotatoReceipt(result_ref="result:0:1", producer_command_index=0)
    with pytest.raises(UnsignedBuilderError) as excinfo:
        check_hot_potato_receipt((build.result.commands[0], repay, duplicate), receipt)
    assert (
        excinfo.value.violations[0].code
        is ConformanceErrorCode.HOT_POTATO_DUPLICATE_DISCHARGE
    )


def test_repay_before_borrow_fails_closed() -> None:
    config = _config(version=1)
    build = build_navi_flashloan_ptb(
        config=config,
        frame=navi_frame(),
        amount=10,
        repay_coin=_repay_coin(),
    )
    borrow, repay = build.result.commands
    receipt = HotPotatoReceipt(result_ref="result:0:1", producer_command_index=0)
    with pytest.raises(UnsignedBuilderError) as excinfo:
        check_hot_potato_receipt((repay, borrow), receipt)
    assert (
        excinfo.value.violations[0].code
        is ConformanceErrorCode.HOT_POTATO_ORDER_INVALID
    )


def test_unknown_config_version_fails_closed() -> None:
    for version in (0, 3, -1):
        with pytest.raises(UnsignedBuilderError) as excinfo:
            _config(version=version)
        assert (
            excinfo.value.violations[0].code is ConformanceErrorCode.PTB_VERSION_UNKNOWN
        )


def test_unverified_config_fails_closed() -> None:
    with pytest.raises(UnsignedBuilderError) as excinfo:
        NaviVerifiedDeploymentConfig(
            package_id=NAVI_PACKAGE,
            storage_id=NAVI_STORAGE,
            flashloan_config_id=NAVI_FLASHLOAN_CONFIG,
            pool_object_id=NAVI_POOL,
            sui_coin_type=NAVI_COIN_TYPE,
            version=2,
            verified=False,
            config_source="not verified",
        )
    assert (
        excinfo.value.violations[0].code is ConformanceErrorCode.SOURCE_PIN_UNVERIFIED
    )


def test_amount_must_be_positive_u64() -> None:
    config = _config(version=2)
    for bad_amount in (0, -1, 1 << 64):
        with pytest.raises(UnsignedBuilderError) as excinfo:
            build_navi_flashloan_ptb(
                config=config,
                frame=navi_frame(),
                amount=bad_amount,
                repay_coin=_repay_coin(),
            )
        assert (
            excinfo.value.violations[0].code is ConformanceErrorCode.PTB_AMOUNT_INVALID
        )


def test_repay_coin_type_mismatch_fails_closed() -> None:
    config = _config(version=2)
    wrong_coin = PtArgument(
        kind="object_id", value=NAVI_REPAY_COIN, type_tag="0x2::usdc::USDC"
    )
    with pytest.raises(UnsignedBuilderError) as excinfo:
        build_navi_flashloan_ptb(
            config=config,
            frame=navi_frame(),
            amount=10,
            repay_coin=wrong_coin,
        )
    assert excinfo.value.violations[0].code is ConformanceErrorCode.COIN_TYPE_MISMATCH


def test_repay_coin_object_conflicts_fail_closed() -> None:
    config = _config(version=2)
    with pytest.raises(UnsignedBuilderError) as missing:
        build_navi_flashloan_ptb(
            config=config,
            frame=navi_frame(),
            amount=10,
            repay_coin=PtArgument(kind="object_id", value="0x" + "99" * 32),
        )
    assert (
        missing.value.violations[0].code
        is ConformanceErrorCode.PTB_REQUIRED_OBJECT_MISSING
    )
    with pytest.raises(UnsignedBuilderError) as shared:
        build_navi_flashloan_ptb(
            config=config,
            frame=navi_frame(repay_coin_kind=SuiObjectKind.SHARED),
            amount=10,
            repay_coin=_repay_coin(),
        )
    assert shared.value.violations[0].code is ConformanceErrorCode.PTB_OBJECT_CONFLICT


def test_repayment_below_principal_fails_closed() -> None:
    config = _config(version=2)
    with pytest.raises(UnsignedBuilderError) as excinfo:
        build_navi_flashloan_ptb(
            config=config,
            frame=navi_frame(),
            amount=100,
            repay_coin=_repay_coin(),
            required_repayment_units=99,
        )
    assert (
        excinfo.value.violations[0].code
        is ConformanceErrorCode.REPAYMENT_BELOW_PRINCIPAL
    )


def test_unknown_required_repayment_is_recorded_not_zeroed() -> None:
    build = build_navi_flashloan_ptb(
        config=_config(version=2),
        frame=navi_frame(),
        amount=10,
        repay_coin=_repay_coin(),
    )
    assert build.required_repayment_units is None
    assert build.principal_units == 10


def test_pure_value_is_never_a_repay_coin() -> None:
    with pytest.raises(UnsignedBuilderError) as excinfo:
        build_navi_flashloan_ptb(
            config=_config(version=2),
            frame=navi_frame(),
            amount=10,
            repay_coin=PtArgument(kind="pure", value="u64:10"),
        )
    assert excinfo.value.violations[0].code is ConformanceErrorCode.INVALID_INPUT


def test_builder_never_uses_forbidden_sign_or_send_calls() -> None:
    """AST-level guarantee: no sign/send/execute/legacy-RPC call sites exist."""

    import ast
    from pathlib import Path

    source = Path("src/lending/unsigned_builders/navi_ptb_builder.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    forbidden_attributes = {
        "executeTransactionBlock",
        "signAndExecuteTransactionBlock",
        "sign",
        "signTransaction",
        "signMessage",
    }
    forbidden_modules = {"urllib", "requests", "http", "socket", "websockets", "grpc"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in forbidden_attributes
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_modules
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in forbidden_modules
    assert NAVI_FORBIDDEN_CALLS == ("tx.sign", "executeTransactionBlock", "jsonRpc")


def test_navi_builder_source_pin_matches_pinned_monorepo() -> None:
    fixture = load_fixture("navi_ptb_golden.json")
    assert NAVI_BUILDER_SOURCE_PIN.verified_offline is True
    assert NAVI_BUILDER_SOURCE_PIN.commit == fixture["source_pin"]["commit"]
    assert NAVI_BUILDER_SOURCE_PIN.version == fixture["source_pin"]["sdk_version"]
    assert NAVI_BUILDER_PROVIDER == "navi"
    assert fixture["sui_system_state_id_literal"] == SUI_SYSTEM_STATE_ID
    assert fixture["sui_clock_id_literal"] == SUI_CLOCK_ID
