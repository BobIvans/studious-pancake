"""R03-C: unsigned NAVI Sui PTB flash-loan builder (v1/v2, hot-potato).

Pinned source: ``naviprotocol/naviprotocol-monorepo`` @ commit
``40d971c8ebd46d2af6c6210c6aaf1521ebefda9b``, package ``@naviprotocol/lending``
version ``2.0.12`` (MIT).  Per the pinned ``flashloan.ts`` / ``config.ts``:

- config version 1 -> ``<package>::lending::flash_loan_with_ctx`` with
  arguments [flashloanConfig, pool, amount(u64)];
- config version 2 -> ``<package>::lending::flash_loan_with_ctx_v2`` with
  arguments [flashloanConfig, pool, amount(u64), 0x05 SuiSystemState];
- repayment (same entry for v1 and v2) ->
  ``<package>::lending::flash_repay_with_ctx`` with arguments
  [0x06 Clock, storage, pool, receipt, repayCoin];
- the borrow call returns [balance, receipt]; the receipt is a hot potato that
  cannot be dropped, duplicated, or discharged by an earlier command.

This module builds a deterministic *unsigned* PTB command model only.  It never
imports a signer, never calls ``tx.sign`` / ``executeTransactionBlock``, never
uses a legacy JSON-RPC transport, and never touches the network.  Object
sharing/kind is validated against an existing :class:`SuiStateFrame` owner
(``src/multichain/sui.py``, read-only reuse) so stale versions or object
conflicts fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Sequence

from src.lending.unsigned_builders.contract import (
    RECEIPT_TYPE_UNKNOWN,
    BuildStatus,
    BuilderSourcePin,
    CapacityStatus,
    ConformanceErrorCode,
    HotPotatoReceipt,
    PtArgument,
    PtBuildResult,
    PtCommand,
    UnsignedBuilderError,
    _validate_object_id as _normalize_object_id,
    canonical_hash,
    check_hot_potato_receipt,
    check_ptb_package,
)
from src.multichain.sui import SuiObjectKind, SuiStateFrame

NAVI_BUILDER_PROVIDER = "navi"
NAVI_BUILDER_CHAIN = "sui"

NAVI_BUILDER_SOURCE_PIN = BuilderSourcePin(
    provider=NAVI_BUILDER_PROVIDER,
    chain=NAVI_BUILDER_CHAIN,
    repository="https://github.com/naviprotocol/naviprotocol-monorepo",
    commit="40d971c8ebd46d2af6c6210c6aaf1521ebefda9b",
    version="2.0.12",
    license_label="MIT (pinned blobs fdb4c0cdb9f8a81c52904f55eaa01e74af0c3982 / "
    "714be41fcf342319da50d93b4d7933fad8e0817d / "
    "a67a742d8a6d41e2e3960f50253f43a6ae2fc573)",
    source_paths=(
        "packages/lending/src/flashloan.ts",
        "packages/lending/src/config.ts",
        "packages/lending/src/types.ts",
    ),
    blob_sha1s=(
        "fdb4c0cdb9f8a81c52904f55eaa01e74af0c3982",
        "714be41fcf342319da50d93b4d7933fad8e0817d",
        "a67a742d8a6d41e2e3960f50253f43a6ae2fc573",
    ),
    verified_offline=True,
)

#: Pinned SDK constants (flashloan.ts / pool.ts): shared singletons by address.
#: The pinned SDK passes the shorthand literals ``0x05`` / ``0x06``; the
#: canonical left-padded forms are used for all comparisons and arguments.
SUI_SYSTEM_STATE_ID = "0x05"
SUI_CLOCK_ID = "0x06"
_SUI_SYSTEM_STATE_NORMALIZED = _normalize_object_id(
    SUI_SYSTEM_STATE_ID, "sui system state"
)
_SUI_CLOCK_NORMALIZED = _normalize_object_id(SUI_CLOCK_ID, "sui clock")
NAVI_LENDING_MODULE = "lending"
NAVI_BORROW_FUNCTION_V1 = "flash_loan_with_ctx"
NAVI_BORROW_FUNCTION_V2 = "flash_loan_with_ctx_v2"
NAVI_REPAY_FUNCTION = "flash_repay_with_ctx"

#: The pinned SDK does not expose the receipt struct name; it is recorded as
#: UNKNOWN (never guessed, never zero).
NAVI_RECEIPT_TYPE = RECEIPT_TYPE_UNKNOWN

#: Safety statement: calls this builder must never perform (no signing, no
#: submission, no legacy JSON-RPC transport).
NAVI_FORBIDDEN_CALLS = ("tx.sign", "executeTransactionBlock", "jsonRpc")

_BORROW_BALANCE_RESULT = "result:0:0"
_BORROW_RECEIPT_RESULT = "result:0:1"


@dataclass(frozen=True, slots=True)
class NaviVerifiedDeploymentConfig:
    """Verified current deployed NAVI lending config (caller-supplied pin).

    ``version`` selects the pinned v1/v2 borrow entry; ``verified`` must be
    True and ``config_source`` must name where the deployed config was verified.
    """

    package_id: str
    storage_id: str
    flashloan_config_id: str
    pool_object_id: str
    sui_coin_type: str
    version: int
    verified: bool
    config_source: str

    def __post_init__(self) -> None:
        from src.lending.unsigned_builders.contract import _validate_object_id

        object.__setattr__(
            self,
            "package_id",
            _validate_object_id(self.package_id, "config package_id"),
        )
        object.__setattr__(
            self,
            "storage_id",
            _validate_object_id(self.storage_id, "config storage_id"),
        )
        object.__setattr__(
            self,
            "flashloan_config_id",
            _validate_object_id(self.flashloan_config_id, "config flashloan_config_id"),
        )
        object.__setattr__(
            self,
            "pool_object_id",
            _validate_object_id(self.pool_object_id, "config pool_object_id"),
        )
        _require_coin_type(self.sui_coin_type)
        if self.version not in (1, 2):
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.PTB_VERSION_UNKNOWN,
                NAVI_BUILDER_PROVIDER,
                f"deployed config version {self.version} is not a known pinned "
                "lending version (1 or 2); refusing to pick a borrow entry",
            )
        if not self.verified:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.SOURCE_PIN_UNVERIFIED,
                NAVI_BUILDER_PROVIDER,
                "deployed config is not verified against current package state",
            )
        if not isinstance(self.config_source, str) or not self.config_source.strip():
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.SOURCE_PIN_UNVERIFIED,
                NAVI_BUILDER_PROVIDER,
                "config_source naming the verification of the deployed config is required",
            )

    @property
    def digest(self) -> str:
        return canonical_hash(self)


def _require_coin_type(value: str) -> str:
    if not isinstance(value, str) or value.count("::") < 2 or not value.strip():
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.COIN_TYPE_MISMATCH,
            NAVI_BUILDER_PROVIDER,
            f"coin type {value!r} is not a fully qualified '0x..::module::Name'",
        )
    return value


@dataclass(frozen=True, slots=True)
class NaviPtbBuild:
    """Provider-level wrapper carrying conformance DTO + exact-unit bindings."""

    result: PtBuildResult
    sui_coin_type: str
    principal_units: int
    required_repayment_units: int | None  # None = UNKNOWN, never 0
    config_version: int
    package_id: str
    config_digest: str
    frame_checkpoint: int | None


def _frame_object(frame: SuiStateFrame, object_id: str):
    normalized = object_id.lower()
    for item in frame.objects:
        if item.object_id.lower() == normalized:
            return item
    return None


def _require_shared_object(frame: SuiStateFrame, object_id: str, label: str) -> None:
    obj = _frame_object(frame, object_id)
    if obj is None:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PTB_REQUIRED_OBJECT_MISSING,
            NAVI_BUILDER_PROVIDER,
            f"{label} object {object_id} is absent from the bound state frame",
        )
    if obj.kind is not SuiObjectKind.SHARED:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PTB_OBJECT_CONFLICT,
            NAVI_BUILDER_PROVIDER,
            f"{label} object {object_id} must be shared, found {obj.kind.value}",
        )


def _require_owned_object(frame: SuiStateFrame, object_id: str, label: str) -> None:
    obj = _frame_object(frame, object_id)
    if obj is None:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PTB_REQUIRED_OBJECT_MISSING,
            NAVI_BUILDER_PROVIDER,
            f"{label} object {object_id} is absent from the bound state frame",
        )
    if obj.kind is not SuiObjectKind.OWNED:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PTB_OBJECT_CONFLICT,
            NAVI_BUILDER_PROVIDER,
            f"{label} object {object_id} must be owned, found {obj.kind.value}",
        )


def build_navi_flashloan_ptb(
    *,
    config: NaviVerifiedDeploymentConfig,
    frame: SuiStateFrame,
    amount: int,
    repay_coin: PtArgument,
    required_repayment_units: int | None = None,
) -> NaviPtbBuild:
    """Build the unsigned v1/v2 flash-loan PTB command model, fail-closed.

    The borrow command produces [balance, receipt]; the repay command must be
    the (single) discharger of the receipt.  Object sharing/kind is validated
    against the bound frame before any command is emitted.
    """

    if not isinstance(frame, SuiStateFrame):
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            NAVI_BUILDER_PROVIDER,
            "a bound SuiStateFrame is required for object sharing/version checks",
        )
    if type(amount) is not int or not 1 <= amount <= (1 << 64) - 1:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PTB_AMOUNT_INVALID,
            NAVI_BUILDER_PROVIDER,
            "flash-loan amount must be a positive u64",
        )
    if required_repayment_units is not None:
        if type(required_repayment_units) is not int:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.INVALID_INPUT,
                NAVI_BUILDER_PROVIDER,
                "required repayment must be integer or None (unknown)",
            )
        if required_repayment_units < amount:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.REPAYMENT_BELOW_PRINCIPAL,
                NAVI_BUILDER_PROVIDER,
                "required repayment cannot be below the borrowed amount",
            )
    if repay_coin.kind == "pure":
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            NAVI_BUILDER_PROVIDER,
            "repay coin must be an object or result reference, not a pure value",
        )
    if repay_coin.type_tag is not None and repay_coin.type_tag != config.sui_coin_type:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.COIN_TYPE_MISMATCH,
            NAVI_BUILDER_PROVIDER,
            "repayment coin type differs from the flash-loan coin type",
        )

    _require_shared_object(frame, config.flashloan_config_id, "flashloan config")
    _require_shared_object(frame, config.pool_object_id, "pool")
    _require_shared_object(frame, config.storage_id, "storage")
    _require_shared_object(frame, _SUI_CLOCK_NORMALIZED, "clock")
    if config.version == 2:
        _require_shared_object(frame, _SUI_SYSTEM_STATE_NORMALIZED, "SuiSystemState")
    if repay_coin.kind == "object_id":
        _require_owned_object(frame, repay_coin.value, "repay coin")

    borrow_arguments = [
        PtArgument(kind="object_id", value=config.flashloan_config_id),
        PtArgument(kind="object_id", value=config.pool_object_id),
        PtArgument(kind="pure", value=f"u64:{amount}"),
    ]
    borrow_function = NAVI_BORROW_FUNCTION_V1
    if config.version == 2:
        borrow_function = NAVI_BORROW_FUNCTION_V2
        borrow_arguments.append(
            PtArgument(kind="object_id", value=_SUI_SYSTEM_STATE_NORMALIZED)
        )
    borrow_command = PtCommand(
        name="navi_flash_loan_borrow",
        target=f"{config.package_id}::{NAVI_LENDING_MODULE}::{borrow_function}",
        type_arguments=(config.sui_coin_type,),
        arguments=tuple(borrow_arguments),
        result_names=("flash_balance", "flash_receipt"),
    )
    repay_command = PtCommand(
        name="navi_flash_loan_repay",
        target=f"{config.package_id}::{NAVI_LENDING_MODULE}::{NAVI_REPAY_FUNCTION}",
        type_arguments=(config.sui_coin_type,),
        arguments=(
            PtArgument(kind="object_id", value=_SUI_CLOCK_NORMALIZED),
            PtArgument(kind="object_id", value=config.storage_id),
            PtArgument(kind="object_id", value=config.pool_object_id),
            PtArgument(kind="result_ref", value=_BORROW_RECEIPT_RESULT),
            repay_coin,
        ),
        result_names=("repay_return_balance",),
    )
    commands = (borrow_command, repay_command)
    receipt = HotPotatoReceipt(
        result_ref=_BORROW_RECEIPT_RESULT,
        producer_command_index=0,
        consumed_by_command_index=1,
        receipt_type=NAVI_RECEIPT_TYPE,
    )

    check_navi_command_shape(config, commands, amount=amount, repay_coin=repay_coin)
    check_ptb_package(commands, config.package_id)
    check_hot_potato_receipt(commands, receipt)

    result = PtBuildResult(
        provider=NAVI_BUILDER_PROVIDER,
        package_id=config.package_id,
        config_version=config.version,
        commands=commands,
        receipt=receipt,
        source_pin=NAVI_BUILDER_SOURCE_PIN,
        build_status=BuildStatus.BUILT_OFFLINE_UNQUALIFIED,
        capacity_status=CapacityStatus.NOT_EVALUATED,
    )
    return NaviPtbBuild(
        result=result,
        sui_coin_type=config.sui_coin_type,
        principal_units=amount,
        required_repayment_units=required_repayment_units,
        config_version=config.version,
        package_id=config.package_id,
        config_digest=config.digest,
        frame_checkpoint=frame.checkpoint,
    )


def check_navi_command_shape(
    config: NaviVerifiedDeploymentConfig,
    commands: Sequence[PtCommand],
    *,
    amount: int,
    repay_coin: PtArgument,
) -> None:
    """Fail-closed exact-shape conformance against the pinned SDK call layouts."""

    if len(commands) != 2:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            NAVI_BUILDER_PROVIDER,
            "NAVI flash-loan PTB requires exactly borrow + repay commands",
        )
    borrow, repay = commands
    expected_borrow_function = (
        NAVI_BORROW_FUNCTION_V2 if config.version == 2 else NAVI_BORROW_FUNCTION_V1
    )
    if (
        borrow.function_name != expected_borrow_function
        or not borrow.target.startswith(f"{config.package_id}::{NAVI_LENDING_MODULE}::")
    ):
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PACKAGE_ID_MISMATCH,
            NAVI_BUILDER_PROVIDER,
            f"borrow target {borrow.target} does not match the pinned "
            f"{expected_borrow_function} path for config version {config.version}",
        )
    if repay.function_name != NAVI_REPAY_FUNCTION or not repay.target.startswith(
        f"{config.package_id}::{NAVI_LENDING_MODULE}::"
    ):
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PACKAGE_ID_MISMATCH,
            NAVI_BUILDER_PROVIDER,
            f"repay target {repay.target} does not match the pinned "
            f"{NAVI_REPAY_FUNCTION} path",
        )
    if borrow.type_arguments != (config.sui_coin_type,) or repay.type_arguments != (
        config.sui_coin_type,
    ):
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.COIN_TYPE_MISMATCH,
            NAVI_BUILDER_PROVIDER,
            "moveCall type arguments must be exactly the flash-loan coin type",
        )
    expected_borrow_arg_count = 4 if config.version == 2 else 3
    if len(borrow.arguments) != expected_borrow_arg_count:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PTB_REQUIRED_OBJECT_MISSING,
            NAVI_BUILDER_PROVIDER,
            f"v{config.version} borrow call requires {expected_borrow_arg_count} arguments",
        )
    _pure_u64_or_fail(borrow.arguments[2], amount)
    if config.version == 2:
        system_state = borrow.arguments[3]
        if (
            system_state.kind != "object_id"
            or system_state.value != _SUI_SYSTEM_STATE_NORMALIZED
        ):
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.PTB_OBJECT_CONFLICT,
                NAVI_BUILDER_PROVIDER,
                "v2 borrow must pass the 0x05 SuiSystemState shared object",
            )
    if len(repay.arguments) != 5:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PTB_REQUIRED_OBJECT_MISSING,
            NAVI_BUILDER_PROVIDER,
            "flash_repay_with_ctx requires exactly 5 arguments",
        )
    clock_arg = repay.arguments[0]
    if clock_arg.kind != "object_id" or clock_arg.value != _SUI_CLOCK_NORMALIZED:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PTB_OBJECT_CONFLICT,
            NAVI_BUILDER_PROVIDER,
            "repay must pass the 0x06 Clock shared object first",
        )
    if (
        repay.arguments[1].kind != "object_id"
        or repay.arguments[1].value != config.storage_id
    ):
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PTB_OBJECT_CONFLICT,
            NAVI_BUILDER_PROVIDER,
            "repay must pass the configured storage object",
        )
    if (
        repay.arguments[2].kind != "object_id"
        or repay.arguments[2].value != config.pool_object_id
    ):
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PTB_OBJECT_CONFLICT,
            NAVI_BUILDER_PROVIDER,
            "repay must pass the configured pool object",
        )
    if (
        repay.arguments[3].kind != "result_ref"
        or repay.arguments[3].value != _BORROW_RECEIPT_RESULT
    ):
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.HOT_POTATO_UNCONSUMED,
            NAVI_BUILDER_PROVIDER,
            "repay must discharge the exact borrow receipt result",
        )
    if repay_coin.kind == "object_id":
        coin_arg = repay.arguments[4]
        if coin_arg.kind != repay_coin.kind or coin_arg.value != repay_coin.value:
            raise UnsignedBuilderError.single(
                ConformanceErrorCode.PTB_OBJECT_CONFLICT,
                NAVI_BUILDER_PROVIDER,
                "repay coin argument differs from the bound repayment coin",
            )
    if (
        borrow.arguments[0].kind != "object_id"
        or borrow.arguments[0].value != config.flashloan_config_id
    ):
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PTB_OBJECT_CONFLICT,
            NAVI_BUILDER_PROVIDER,
            "borrow must pass the configured flashloan config object",
        )
    if (
        borrow.arguments[1].kind != "object_id"
        or borrow.arguments[1].value != config.pool_object_id
    ):
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PTB_OBJECT_CONFLICT,
            NAVI_BUILDER_PROVIDER,
            "borrow must pass the configured pool object",
        )


def _pure_u64_or_fail(argument: PtArgument, expected: int) -> None:
    if argument.kind != "pure" or not argument.value.startswith("u64:"):
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.PTB_AMOUNT_INVALID,
            NAVI_BUILDER_PROVIDER,
            "borrow amount must be a pure u64 argument",
        )
    actual = int(argument.value.split(":", 1)[1])
    if actual != expected:
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.AMOUNT_MISMATCH,
            NAVI_BUILDER_PROVIDER,
            f"encoded borrow amount {actual} differs from requested {expected}",
        )


def canonical_ptb_payload(build: NaviPtbBuild) -> dict:
    """Deterministic JSON-able payload of the built PTB (golden-fixture form)."""

    from src.lending.unsigned_builders.contract import _canonical_payload

    payload = _canonical_payload(build.result)
    if not isinstance(payload, dict):
        raise UnsignedBuilderError.single(
            ConformanceErrorCode.INVALID_INPUT,
            NAVI_BUILDER_PROVIDER,
            "canonical payload must be a mapping",
        )
    return payload


def canonical_ptb_json(build: NaviPtbBuild) -> str:
    """Deterministic JSON serialization used for offline golden comparison."""

    return json.dumps(
        canonical_ptb_payload(build),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def build_navi_unconsumed_receipt_probe(
    config: NaviVerifiedDeploymentConfig,
    frame: SuiStateFrame,
    amount: int,
    repay_coin: PtArgument,
) -> tuple[PtCommand, ...]:
    """Deliberately build a borrow-only command tuple for negative tests.

    Used to demonstrate the fail-closed hot-potato checks; never returned as a
    valid build result.
    """

    borrow_arguments = [
        PtArgument(kind="object_id", value=config.flashloan_config_id),
        PtArgument(kind="object_id", value=config.pool_object_id),
        PtArgument(kind="pure", value=f"u64:{amount}"),
    ]
    borrow_function = (
        NAVI_BORROW_FUNCTION_V2 if config.version == 2 else NAVI_BORROW_FUNCTION_V1
    )
    if config.version == 2:
        borrow_arguments.append(
            PtArgument(kind="object_id", value=_SUI_SYSTEM_STATE_NORMALIZED)
        )
    return (
        PtCommand(
            name="navi_flash_loan_borrow",
            target=f"{config.package_id}::{NAVI_LENDING_MODULE}::{borrow_function}",
            type_arguments=(config.sui_coin_type,),
            arguments=tuple(borrow_arguments),
            result_names=("flash_balance", "flash_receipt"),
        ),
    )


__all__ = [
    "NAVI_BORROW_FUNCTION_V1",
    "NAVI_BORROW_FUNCTION_V2",
    "NAVI_BUILDER_CHAIN",
    "NAVI_BUILDER_PROVIDER",
    "NAVI_BUILDER_SOURCE_PIN",
    "NAVI_FORBIDDEN_CALLS",
    "NAVI_LENDING_MODULE",
    "NAVI_RECEIPT_TYPE",
    "NAVI_REPAY_FUNCTION",
    "NaviPtbBuild",
    "NaviVerifiedDeploymentConfig",
    "SUI_CLOCK_ID",
    "SUI_SYSTEM_STATE_ID",
    "build_navi_flashloan_ptb",
    "build_navi_unconsumed_receipt_probe",
    "canonical_ptb_json",
    "canonical_ptb_payload",
    "check_navi_command_shape",
]
