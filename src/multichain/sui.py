"""AGG-11 CHAIN-04: Sui object/PTB and flash-liquidity semantics.

R02-CAP-C addition: a strictly read-only NAVI shared-pool capacity reader (see
the reader section below). It decodes caller-supplied offline object/checkpoint
captures only; it performs no I/O, holds no signer/sender authority, and never
qualifies a FlashCapitalEdge. ``getAllFlashLoanAssets`` output is demoted to an
explicit DISCOVERY-only evidence state in the data model, and effective flash
borrow capacity stays UNKNOWN (never zero) until a governed gRPC/GraphQL
checkpoint-consistent live read with independent quorum is authorized.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, fields as dataclass_fields
from dataclasses import is_dataclass
from enum import StrEnum
from fractions import Fraction
import hashlib
import json

from .core import AssetRef, DeploymentRef, ExactAssetAmount, MultiChainError


def _object_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise MultiChainError("SUI_OBJECT_ID_INVALID", f"{field} needs 0x id")
    body = value[2:].lower()
    if len(body) != 64 or any(char not in "0123456789abcdef" for char in body):
        raise MultiChainError("SUI_OBJECT_ID_INVALID", f"{field} must be 32 bytes")
    return "0x" + body


def _uint(value: object, field: str, bits: int = 64) -> int:
    if type(value) is not int or not 0 <= value < (1 << bits):
        raise MultiChainError("SUI_UINT_INVALID", f"{field} must fit u{bits}")
    return value


class SuiObjectKind(StrEnum):
    OWNED = "owned"
    SHARED = "shared"
    IMMUTABLE = "immutable"


@dataclass(frozen=True, slots=True)
class SuiObjectRef:
    object_id: str
    version: int
    digest: str
    kind: SuiObjectKind
    type_tag: str
    balance_units: int | None = None

    def __post_init__(self) -> None:
        _object_id(self.object_id, "object_id")
        _uint(self.version, "version")
        if not self.digest:
            raise MultiChainError("SUI_DIGEST_REQUIRED", "object digest required")
        if not self.type_tag:
            raise MultiChainError("SUI_TYPE_REQUIRED", "object type tag required")
        if self.balance_units is not None:
            _uint(self.balance_units, "balance_units", bits=256)


@dataclass(frozen=True, slots=True)
class SuiStateFrame:
    chain_key: str
    checkpoint: int
    epoch: int
    objects: tuple[SuiObjectRef, ...]

    def __post_init__(self) -> None:
        if not self.chain_key:
            raise MultiChainError("CHAIN_KEY_REQUIRED", "Sui chain key required")
        _uint(self.checkpoint, "checkpoint")
        _uint(self.epoch, "epoch")
        ids = [item.object_id.lower() for item in self.objects]
        if len(ids) != len(set(ids)):
            raise MultiChainError("SUI_DUPLICATE_OBJECT", "frame has duplicate object")

    def require_object(self, object_id: str, version: int) -> SuiObjectRef:
        normalized = _object_id(object_id, "object_id")
        for item in self.objects:
            if item.object_id.lower() == normalized:
                if item.version != version:
                    raise MultiChainError(
                        "SUI_STALE_OBJECT_VERSION",
                        "object version is stale",
                    )
                return item
        raise MultiChainError("SUI_OBJECT_MISSING", "required object not in frame")


@dataclass(frozen=True, slots=True)
class SuiHotPotatoObligation:
    obligation_id: str
    protocol: str
    principal: ExactAssetAmount
    repayment_units: int
    receipt_type: str
    deployment: DeploymentRef

    def __post_init__(self) -> None:
        if not self.obligation_id or not self.receipt_type:
            raise MultiChainError(
                "SUI_OBLIGATION_INVALID",
                "obligation id and receipt type required",
            )
        _uint(self.repayment_units, "repayment_units", bits=256)
        if self.repayment_units < self.principal.units:
            raise MultiChainError(
                "SUI_REPAYMENT_BELOW_PRINCIPAL",
                "repayment cannot be below principal",
            )
        if self.deployment.protocol != self.protocol:
            raise MultiChainError(
                "SUI_PROTOCOL_DEPLOYMENT_MISMATCH",
                "obligation deployment mismatch",
            )
        if self.principal.asset.chain_key != self.deployment.chain_key:
            raise MultiChainError(
                "SUI_OBLIGATION_CHAIN_MISMATCH",
                "obligation asset belongs to another chain",
            )


@dataclass(frozen=True, slots=True)
class SuiPtbOperation:
    name: str
    package_id: str
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    discharges: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise MultiChainError("SUI_OPERATION_NAME_REQUIRED", "name required")
        _object_id(self.package_id, "package_id")


@dataclass(frozen=True, slots=True)
class SuiPtbPlan:
    chain_key: str
    checkpoint: int
    gas_object_id: str
    gas_object_version: int
    gas_budget_mist: int
    operations: tuple[SuiPtbOperation, ...]
    obligations: tuple[SuiHotPotatoObligation, ...]
    shared_object_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _object_id(self.gas_object_id, "gas_object_id")
        _uint(self.gas_object_version, "gas_object_version")
        _uint(self.gas_budget_mist, "gas_budget_mist", bits=256)
        if not self.operations:
            raise MultiChainError("SUI_OPERATIONS_REQUIRED", "PTB needs operations")
        obligation_ids = [item.obligation_id for item in self.obligations]
        if len(obligation_ids) != len(set(obligation_ids)):
            raise MultiChainError(
                "SUI_DUPLICATE_OBLIGATION_ID",
                "each hot-potato obligation needs a unique identity",
            )


class SuiPtbAdapter:
    """Compile a deterministic PTB proof without signing or sending."""

    @staticmethod
    def compile(frame: SuiStateFrame, plan: SuiPtbPlan) -> tuple[str, ...]:
        if plan.chain_key != frame.chain_key or plan.checkpoint != frame.checkpoint:
            raise MultiChainError(
                "SUI_FRAME_SCOPE_MISMATCH",
                "PTB is bound to another chain/checkpoint",
            )
        gas = frame.require_object(plan.gas_object_id, plan.gas_object_version)
        if gas.kind is not SuiObjectKind.OWNED:
            raise MultiChainError("SUI_GAS_OBJECT_NOT_OWNED", "gas must be owned")
        if gas.balance_units is not None and gas.balance_units < plan.gas_budget_mist:
            raise MultiChainError(
                "SUI_GAS_BUDGET_UNFUNDED",
                "gas object cannot fund budget",
            )
        consumed: set[str] = set()
        produced: set[str] = set()
        discharged: set[str] = set()
        for operation in plan.operations:
            for object_id in operation.consumes:
                normalized = _object_id(object_id, "consumed_object")
                if normalized == plan.gas_object_id.lower():
                    raise MultiChainError(
                        "SUI_GAS_OBJECT_REUSED",
                        "gas object cannot be consumed as a trade object",
                    )
                if normalized in consumed:
                    raise MultiChainError(
                        "SUI_OBJECT_DOUBLE_CONSUME",
                        "linear object consumed twice",
                    )
                consumed.add(normalized)
            for object_id in operation.produces:
                normalized = _object_id(object_id, "produced_object")
                if normalized in produced:
                    raise MultiChainError(
                        "SUI_OBJECT_DOUBLE_PRODUCE",
                        "linear result produced twice",
                    )
                produced.add(normalized)
            for obligation_id in operation.discharges:
                if obligation_id in discharged:
                    raise MultiChainError(
                        "SUI_OBLIGATION_DOUBLE_DISCHARGE",
                        "obligation discharged twice",
                    )
                discharged.add(obligation_id)
        expected = {item.obligation_id for item in plan.obligations}
        if discharged != expected:
            raise MultiChainError(
                "SUI_HOT_POTATO_NOT_CLOSED",
                "all borrow/flash receipts must be discharged in the same PTB",
                stage="settlement",
            )
        for object_id in plan.shared_object_ids:
            obj = frame.require_object(
                object_id,
                next(
                    item.version
                    for item in frame.objects
                    if item.object_id.lower()
                    == _object_id(
                        object_id,
                        "shared_object",
                    )
                ),
            )
            if obj.kind is not SuiObjectKind.SHARED:
                raise MultiChainError(
                    "SUI_SHARED_OBJECT_KIND_INVALID",
                    "declared shared object is not shared",
                )
        return tuple(operation.name for operation in plan.operations)


class DeepBookFinancingAdapter:
    @staticmethod
    def prepare(
        *,
        deployment: DeploymentRef,
        principal: ExactAssetAmount,
        pool_capacity: int,
        same_pool_trade_input: int,
        fee_units: int,
        receipt_type: str,
    ) -> SuiHotPotatoObligation:
        if deployment.protocol != "deepbook":
            raise MultiChainError("DEEPBOOK_DEPLOYMENT_REQUIRED", "wrong package")
        _uint(pool_capacity, "pool_capacity", bits=256)
        _uint(same_pool_trade_input, "same_pool_trade_input", bits=256)
        _uint(fee_units, "fee_units", bits=256)
        if principal.units + same_pool_trade_input > pool_capacity:
            raise MultiChainError(
                "DEEPBOOK_SHARED_CAPACITY_EXCEEDED",
                "loan and order-book use share pool capacity",
            )
        return SuiHotPotatoObligation(
            obligation_id="deepbook-flash",
            protocol="deepbook",
            principal=principal,
            repayment_units=principal.units + fee_units,
            receipt_type=receipt_type,
            deployment=deployment,
        )


class CetusFlashKind(StrEnum):
    FLASH_LOAN = "flash-loan"
    FLASH_SWAP = "flash-swap"


class CetusFinancingAdapter:
    @staticmethod
    def prepare(
        *,
        deployment: DeploymentRef,
        kind: CetusFlashKind,
        principal: ExactAssetAmount,
        fee_units: int,
    ) -> SuiHotPotatoObligation:
        if deployment.protocol != "cetus":
            raise MultiChainError("CETUS_DEPLOYMENT_REQUIRED", "wrong package")
        _uint(fee_units, "fee_units", bits=256)
        receipt = {
            CetusFlashKind.FLASH_LOAN: "cetus::flash_loan::Receipt",
            CetusFlashKind.FLASH_SWAP: "cetus::flash_swap::Receipt",
        }[kind]
        return SuiHotPotatoObligation(
            obligation_id=f"cetus:{kind.value}",
            protocol="cetus",
            principal=principal,
            repayment_units=principal.units + fee_units,
            receipt_type=receipt,
            deployment=deployment,
        )


class SuiAdditionalFinancingAdapter:
    """NAVI/Scallop/Bucket share shape but never share receipt identity."""

    ALLOWED = frozenset({"navi", "scallop", "bucket"})

    @classmethod
    def prepare(
        cls,
        *,
        deployment: DeploymentRef,
        principal: ExactAssetAmount,
        available_capacity: int,
        fee_units: int,
        receipt_type: str,
    ) -> SuiHotPotatoObligation:
        if deployment.protocol not in cls.ALLOWED:
            raise MultiChainError(
                "SUI_PROTOCOL_UNSUPPORTED",
                "expected NAVI, Scallop or Bucket",
            )
        _uint(available_capacity, "available_capacity", bits=256)
        _uint(fee_units, "fee_units", bits=256)
        if principal.units > available_capacity:
            raise MultiChainError(
                "SUI_PROTOCOL_CAPACITY_EXCEEDED",
                "principal exceeds proven protocol capacity",
            )
        if not receipt_type.startswith(deployment.protocol + "::"):
            raise MultiChainError(
                "SUI_RECEIPT_PROTOCOL_MISMATCH",
                "receipt identity is not interchangeable across protocols",
            )
        return SuiHotPotatoObligation(
            obligation_id=f"{deployment.protocol}:flash",
            protocol=deployment.protocol,
            principal=principal,
            repayment_units=principal.units + fee_units,
            receipt_type=receipt_type,
            deployment=deployment,
        )


# ---------------------------------------------------------------------------
# R02-CAP-C: NAVI (Sui) read-only shared-pool capacity reader.
#
# Pinned upstream (offline vendor pack, git blob SHA-1 over exact LF bytes,
# verified against docs/roadmap/r02-capacity-recovery-2026-10-08/offline/
# VENDOR_MANIFEST.json):
# - repository: naviprotocol/naviprotocol-monorepo
# - commit: 40d971c8ebd46d2af6c6210c6aaf1521ebefda9b
# - package: @naviprotocol/lending 2.0.12 (MIT); legacy navi-sdk is NOT used.
# The historic naviprotocol/protocol-interface@31d6401e298a10adb6b0e09c6137ab
# 6d7024f08c flash_loan.move is structural only and does NOT prove the current
# deployed package ABI, so NAVI pool object field layouts stay unpinned here.
#
# Semantics proven offline come from actual captured object state only:
# envelope identity (id/version/digest/type tag/owner), the pool object type
# parameter coin binding, decimals via the framework-pinned 0x2::coin::
# CoinMetadata<T> BCS layout, and the config.version selection between the
# pinned v1/v2 flash entry points. Raw captured pool resource fields are
# recorded with UNAUDITED_SEMANTICS markers and are never capacity; on-chain
# flash limits and fee-config layouts are unpinned, so effective capacity is
# structurally None (unknown is not zero). Qualified edges are gated behind
# governed gRPC/GraphQL checkpoint-consistent live reads, typed
# LIVE_SUI_CHECKPOINT_NOT_AUTHORIZED. Sui legacy JSON-RPC was retired
# (July 2026) and fails closed. Zero network, zero signing, zero sending.
# ---------------------------------------------------------------------------

NAVI_UPSTREAM_REPOSITORY = "naviprotocol/naviprotocol-monorepo"
NAVI_UPSTREAM_COMMIT = "40d971c8ebd46d2af6c6210c6aaf1521ebefda9b"
NAVI_LENDING_SDK_PACKAGE = "@naviprotocol/lending"
NAVI_LENDING_SDK_VERSION = "2.0.12"
NAVI_PROTOCOL_INTERFACE_COMMIT = "31d6401e298a10adb6b0e09c6137ab6d7024f08c"
NAVI_BRIDGE_FACTS_BLOB = "a4b6dd59e77c61e02e08e943e0e9ae981574aac0"
# Git blob SHA-1 (LF bytes) of the vendored offline SDK reference files.
NAVI_VENDOR_BLOB_SHA: dict[str, str] = {
    "offline/vendor/navi/config.ts.txt": "714be41fcf342319da50d93b4d7933fad8e0817d",
    "offline/vendor/navi/flashloan.ts.txt": "fdb4c0cdb9f8a81c52904f55eaa01e74af0c3982",
    "offline/vendor/navi/LICENSE.txt": "feb00aadb1e21c510b3c5ae877fc0f2dada769e7",
    "offline/vendor/navi/package.json.txt": "ae7818ad936c8b19099f650bd4bb795e48c12c13",
    "offline/vendor/navi/pool.ts.txt": "00803355077b90e01484fa31dba42dc38513f629",
    "offline/vendor/navi/types.ts.txt": "a67a742d8a6d41e2e3960f50253f43a6ae2fc573",
}

NAVI_SUI_SYSTEM_STATE_ID = "0x05"
NAVI_CLOCK_ID = "0x06"
NAVI_FLASH_ENTRY_V1 = "lending::flash_loan_with_ctx"
NAVI_FLASH_ENTRY_V2 = "lending::flash_loan_with_ctx_v2"
NAVI_FLASH_REPAY_ENTRY = "lending::flash_repay_with_ctx"

NAVI_READER_DECODER_IDENTITY = "navi.sui.pool-capacity-reader.v1"
NAVI_READER_DECODER_GENERATION = 1
NAVI_READER_EXECUTION_AUTHORITY = "NONE"

NAVI_MAX_DISCOVERY_ROWS = 4096

_SUI_FRAMEWORK_PACKAGE = (
    "0x0000000000000000000000000000000000000000000000000000000000000002"
)
_COIN_METADATA_MODULE = "coin::CoinMetadata"


class NaviCapacityRejectionCode(StrEnum):
    """Typed R02-CAP-C fail-closed negatives (structural and gating)."""

    PACKAGE_ID_MISMATCH = "R02CAPC_PACKAGE_ID_MISMATCH"
    PACKAGE_VERSION_UNKNOWN = "R02CAPC_PACKAGE_VERSION_UNKNOWN"
    OBJECT_VERSION_BINDING_MISSING = "R02CAPC_OBJECT_VERSION_BINDING_MISSING"
    OBJECT_DIGEST_REQUIRED = "R02CAPC_OBJECT_DIGEST_REQUIRED"
    CHECKPOINT_MISMATCH = "R02CAPC_CHECKPOINT_MISMATCH"
    SHARED_OBJECT_OWNER_MISMATCH = "R02CAPC_SHARED_OBJECT_OWNER_MISMATCH"
    COIN_METADATA_OWNER_MISMATCH = "R02CAPC_COIN_METADATA_OWNER_MISMATCH"
    POOL_OBJECT_TYPE_MISMATCH = "R02CAPC_POOL_OBJECT_TYPE_MISMATCH"
    POOL_COIN_TYPE_UNPROVEN = "R02CAPC_POOL_COIN_TYPE_UNPROVEN"
    COIN_TYPE_MISMATCH = "R02CAPC_REVIEWED_COIN_TYPE_MISMATCH"
    COIN_METADATA_LAYOUT_MISMATCH = "R02CAPC_COIN_METADATA_LAYOUT_MISMATCH"
    COIN_DECIMALS_UNPROVEN = "R02CAPC_COIN_DECIMALS_UNPROVEN"
    POOL_MOVE_LAYOUT_UNPINNED = "R02CAPC_POOL_MOVE_LAYOUT_UNPINNED"
    FEE_CONFIG_LAYOUT_UNPINNED = "R02CAPC_FEE_CONFIG_LAYOUT_UNPINNED"
    FLASH_LIMIT_ONCHAIN_UNPINNED = "R02CAPC_ONCHAIN_FLASH_LIMIT_UNPINNED"
    API_DISCOVERY_NOT_ONCHAIN = "NAVI_API_ONLY_NOT_ONCHAIN"
    API_DISCOVERY_ROW_SCHEMA_DRIFT = "R02CAPC_API_DISCOVERY_ROW_SCHEMA_DRIFT"
    API_DISCOVERY_FLOAT_PRECISION = "R02CAPC_API_DISCOVERY_FLOAT_PRECISION_LOSS"
    JSONRPC_TRANSPORT_FORBIDDEN = "R02CAPC_JSONRPC_TRANSPORT_FORBIDDEN"
    MISSING_EFFECTIVE_FLASH_CAP = "MISSING_EFFECTIVE_FLASH_CAP"
    LIVE_SUI_CHECKPOINT_NOT_AUTHORIZED = "LIVE_SUI_CHECKPOINT_NOT_AUTHORIZED"
    GRAPH_ALLOWANCE_PENDING = (
        "R02CAPC_FLASH_CAPITAL_GRAPH_ALLOWANCE_PENDING_INDEPENDENT_QUORUM"
    )


class NaviCapacityEvidenceState(StrEnum):
    """Where a NAVI capacity claim could ever come from.

    DISCOVERY_ONLY_OFFCHAIN_API is the explicit demotion of the
    ``getAllFlashLoanAssets`` response: it is off-chain SDK discovery and is
    structurally barred from producing capacity rows. ONCHAIN_OBJECT_STATE_
    PROVEN is reserved for a future governed gRPC/GraphQL live wave; nothing
    in this module can construct it today.
    """

    DISCOVERY_ONLY_OFFCHAIN_API = "DISCOVERY_ONLY_OFFCHAIN_API"
    OFFLINE_FIXTURE_NOT_ROOTED = "OFFLINE_FIXTURE_NOT_ROOTED"
    ONCHAIN_OBJECT_STATE_PROVEN = "ONCHAIN_OBJECT_STATE_PROVEN"


class NaviSuiReadTransport(StrEnum):
    """Sui read transports. JSON-RPC is retired and fails closed."""

    GOVERNED_GRPC = "GOVERNED_GRPC"
    GOVERNED_GRAPHQL = "GOVERNED_GRAPHQL"
    OFFLINE_FIXTURE_CAPTURE = "OFFLINE_FIXTURE_CAPTURE"
    SUI_JSONRPC = "SUI_JSONRPC"


class NaviCapacityDerivation(StrEnum):
    """How an effective capacity value was proven. Only UNPROVEN exists today."""

    UNPROVEN = "R02CAPC_CAPACITY_DERIVATION_UNPROVEN"


def _type_address(value: str, field: str) -> str:
    """Normalize a Sui type-tag address (short 0x2 forms allowed) to 64 hex.

    Mirrors the frozen graph owner's canonical_identifier padding exactly.
    """

    if not isinstance(value, str) or not value.lower().startswith("0x"):
        raise MultiChainError("SUI_TYPE_ADDRESS_INVALID", f"{field} needs 0x id")
    body = value[2:].lower()
    if (
        not body
        or len(body) > 64
        or any(char not in "0123456789abcdef" for char in body)
    ):
        raise MultiChainError(
            "SUI_TYPE_ADDRESS_INVALID", f"{field} must be 1..64 hex bytes"
        )
    return "0x" + body.rjust(64, "0")


def _full_coin_type(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise MultiChainError("SUI_COIN_TYPE_INVALID", f"{field} must be text")
    parts = value.split("::")
    if len(parts) != 3:
        raise MultiChainError(
            "SUI_COIN_TYPE_INVALID", f"{field} must be 0x..::module::name"
        )
    address = _type_address(parts[0], field)
    module, name = parts[1], parts[2]
    if (
        not module
        or not name
        or any(not ch.isalnum() and ch != "_" for ch in module + name)
    ):
        raise MultiChainError("SUI_COIN_TYPE_INVALID", f"{field} identifiers invalid")
    return f"{address}::{module}::{name}"


def _split_type_tag(type_tag: str) -> tuple[str, str, str, tuple[str, ...]]:
    """Split a Sui struct type tag into (address, module, name, type params).

    Generic parameters are split only at the top nesting level; deeper angle
    brackets stay inside a parameter string.
    """

    if not isinstance(type_tag, str) or not type_tag:
        raise MultiChainError("SUI_TYPE_REQUIRED", "type tag required")
    head = type_tag
    params: list[str] = []
    if type_tag.endswith(">"):
        start = type_tag.find("<")
        if start <= 0:
            raise MultiChainError("SUI_TYPE_INVALID", "malformed generic type tag")
        head = type_tag[:start]
        inner = type_tag[start + 1 : -1]
        depth = 0
        current = ""
        for char in inner:
            if char == "<":
                depth += 1
            elif char == ">":
                if depth == 0:
                    raise MultiChainError(
                        "SUI_TYPE_INVALID", "unbalanced generic brackets"
                    )
                depth -= 1
            if char == "," and depth == 0:
                params.append(current.strip())
                current = ""
            else:
                current += char
        if current.strip():
            params.append(current.strip())
    parts = head.split("::")
    if len(parts) != 3:
        raise MultiChainError("SUI_TYPE_INVALID", "type tag must be 0x..::m::N")
    address = _type_address(parts[0], "type_tag_address")
    module, name = parts[1], parts[2]
    if not module or not name:
        raise MultiChainError("SUI_TYPE_INVALID", "type tag module/name required")
    return address, module, name, tuple(params)


def _decimal_string(value: object, field: str) -> str:
    """Exact decimal string guard; floats are rejected (precision loss)."""

    if isinstance(value, float):
        raise MultiChainError(
            NaviCapacityRejectionCode.API_DISCOVERY_FLOAT_PRECISION.value,
            f"{field} arrives as a JS float; bridge must serialize an exact "
            "decimal string",
            stage="capacity_reading",
        )
    if not isinstance(value, str) or not value:
        raise MultiChainError(
            NaviCapacityRejectionCode.API_DISCOVERY_ROW_SCHEMA_DRIFT.value,
            f"{field} must be a non-empty decimal string",
            stage="capacity_reading",
        )
    body = value[1:] if value.startswith("-") else value
    if not body.isdigit():
        raise MultiChainError(
            NaviCapacityRejectionCode.API_DISCOVERY_ROW_SCHEMA_DRIFT.value,
            f"{field} must be a plain decimal string",
            stage="capacity_reading",
        )
    return value


def _bcs_uleb128(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise MultiChainError(
                NaviCapacityRejectionCode.COIN_METADATA_LAYOUT_MISMATCH.value,
                "truncated BCS varint",
                stage="capacity_reading",
            )
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
        if shift > 35:
            raise MultiChainError(
                NaviCapacityRejectionCode.COIN_METADATA_LAYOUT_MISMATCH.value,
                "BCS varint too long",
                stage="capacity_reading",
            )


def _bcs_string(data: bytes, offset: int) -> tuple[str, int]:
    length, offset = _bcs_uleb128(data, offset)
    if offset + length > len(data):
        raise MultiChainError(
            NaviCapacityRejectionCode.COIN_METADATA_LAYOUT_MISMATCH.value,
            "truncated BCS string",
            stage="capacity_reading",
        )
    return data[offset : offset + length].decode("utf-8"), offset + length


@dataclass(frozen=True, slots=True)
class NaviSuiCheckpointBinding:
    """Recorded capture context. Binding all object captures to one checkpoint
    is an internal consistency requirement, never a rootedness claim."""

    chain_key: str
    checkpoint: int
    digest: str
    epoch: int

    def __post_init__(self) -> None:
        if not isinstance(self.chain_key, str) or not self.chain_key.strip():
            raise MultiChainError("CHAIN_KEY_REQUIRED", "Sui chain key required")
        _uint(self.checkpoint, "checkpoint", bits=64)
        _uint(self.epoch, "epoch", bits=64)
        if not isinstance(self.digest, str) or not self.digest:
            raise MultiChainError(
                NaviCapacityRejectionCode.OBJECT_DIGEST_REQUIRED.value,
                "checkpoint digest required",
                stage="capacity_reading",
            )


@dataclass(frozen=True, slots=True)
class NaviObjectCapture:
    """One captured Sui object envelope plus optional raw content fields.

    ``version`` and ``digest`` are mandatory: a capture without an object
    version binding fails closed. ``fields_raw`` holds raw values captured
    from actual object content as (field path, decimal string) pairs with
    UNAUDITED_SEMANTICS semantics; they are never capacity.
    """

    object_id: str
    version: int
    digest: str
    type_tag: str
    owner_kind: SuiObjectKind
    checkpoint: int
    epoch: int
    fields_raw: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "object_id", _object_id(self.object_id, "object_id"))
        _uint(self.version, "version", bits=64)
        if self.version < 1:
            raise MultiChainError(
                NaviCapacityRejectionCode.OBJECT_VERSION_BINDING_MISSING.value,
                "object capture without a version binding",
                stage="capacity_reading",
            )
        if not isinstance(self.digest, str) or not self.digest:
            raise MultiChainError(
                NaviCapacityRejectionCode.OBJECT_DIGEST_REQUIRED.value,
                "object capture without a digest binding",
                stage="capacity_reading",
            )
        if not isinstance(self.type_tag, str) or not self.type_tag:
            raise MultiChainError(
                "SUI_TYPE_REQUIRED", "object capture type tag required"
            )
        if not isinstance(self.owner_kind, SuiObjectKind):
            raise MultiChainError(
                "SUI_OBJECT_KIND_INVALID", "object owner kind invalid"
            )
        _uint(self.checkpoint, "checkpoint", bits=64)
        _uint(self.epoch, "epoch", bits=64)
        normalized: list[tuple[str, str]] = []
        for path, raw_value in self.fields_raw:
            if not isinstance(path, str) or not path.strip():
                raise MultiChainError(
                    NaviCapacityRejectionCode.POOL_MOVE_LAYOUT_UNPINNED.value,
                    "raw field path must be non-empty text",
                    stage="capacity_reading",
                )
            normalized.append((path.strip(), _decimal_string(raw_value, path)))
        object.__setattr__(self, "fields_raw", tuple(normalized))


@dataclass(frozen=True, slots=True)
class NaviMarketConfigCapture:
    """Pinned-shape lending market config from the captured object state.

    ``version`` is the on-chain lending protocol version the pinned SDK
    selects on: 1 -> flash_loan_with_ctx, 2 -> flash_loan_with_ctx_v2 (adds
    the 0x05 SuiSystemState dependency). Any other version fails closed.
    """

    package: str
    version: int
    storage: NaviObjectCapture
    flashloan_config: NaviObjectCapture

    def __post_init__(self) -> None:
        object.__setattr__(self, "package", _object_id(self.package, "package"))
        if self.version not in (1, 2):
            raise MultiChainError(
                NaviCapacityRejectionCode.PACKAGE_VERSION_UNKNOWN.value,
                "lending config version must be 1 or 2 per the pinned SDK helper",
                stage="capacity_reading",
            )
        for capture in (self.storage, self.flashloan_config):
            if capture.owner_kind is not SuiObjectKind.SHARED:
                raise MultiChainError(
                    NaviCapacityRejectionCode.SHARED_OBJECT_OWNER_MISMATCH.value,
                    "market config dependency objects must be shared",
                    stage="capacity_reading",
                )


@dataclass(frozen=True, slots=True)
class NaviCoinMetadataState:
    """Decimals proven from actual 0x2::coin::CoinMetadata<T> object bytes."""

    coin_type: str
    decimals: int
    name: str
    symbol: str
    description: str
    icon_url: str | None


def decode_navi_coin_metadata(
    data: bytes,
    *,
    type_tag: str,
    owner_kind: SuiObjectKind,
    expected_coin_type: str,
) -> NaviCoinMetadataState:
    """Fail-closed BCS decode of the pinned framework CoinMetadata layout.

    BCS: id (UID, 32-byte address), decimals (u8), name (string), symbol
    (string), description (string), icon_url (Option<string>). Truncated,
    trailing or wrong-binding bytes fail closed instead of guessing.
    """

    address, module, name, params = _split_type_tag(type_tag)
    if module != "coin" or name != "CoinMetadata":
        raise MultiChainError(
            NaviCapacityRejectionCode.COIN_METADATA_LAYOUT_MISMATCH.value,
            "coin metadata capture type tag is not 0x2::coin::CoinMetadata<..>",
            stage="capacity_reading",
        )
    if address != _SUI_FRAMEWORK_PACKAGE or len(params) != 1:
        raise MultiChainError(
            NaviCapacityRejectionCode.COIN_METADATA_LAYOUT_MISMATCH.value,
            "coin metadata capture must be the framework type with one parameter",
            stage="capacity_reading",
        )
    coin_type = _full_coin_type(params[0], "coin_type_parameter")
    if coin_type != _full_coin_type(expected_coin_type, "expected_coin_type"):
        raise MultiChainError(
            NaviCapacityRejectionCode.COIN_TYPE_MISMATCH.value,
            "coin metadata binds another coin type than the reviewed pool coin",
            stage="capacity_reading",
        )
    if owner_kind is not SuiObjectKind.IMMUTABLE:
        raise MultiChainError(
            NaviCapacityRejectionCode.COIN_METADATA_OWNER_MISMATCH.value,
            "coin metadata object is not immutable",
            stage="capacity_reading",
        )
    raw = bytes(data)
    if len(raw) < 33:
        raise MultiChainError(
            NaviCapacityRejectionCode.COIN_METADATA_LAYOUT_MISMATCH.value,
            "coin metadata shorter than the pinned framework layout",
            stage="capacity_reading",
        )
    decimals = raw[32]
    offset = 33
    text_name, offset = _bcs_string(raw, offset)
    text_symbol, offset = _bcs_string(raw, offset)
    text_description, offset = _bcs_string(raw, offset)
    if offset >= len(raw):
        raise MultiChainError(
            NaviCapacityRejectionCode.COIN_METADATA_LAYOUT_MISMATCH.value,
            "coin metadata truncated before icon_url option",
            stage="capacity_reading",
        )
    option_flag = raw[offset]
    offset += 1
    icon_url: str | None = None
    if option_flag == 1:
        icon_url, offset = _bcs_string(raw, offset)
    elif option_flag != 0:
        raise MultiChainError(
            NaviCapacityRejectionCode.COIN_METADATA_LAYOUT_MISMATCH.value,
            "unknown Option encoding for icon_url",
            stage="capacity_reading",
        )
    if offset != len(raw):
        raise MultiChainError(
            NaviCapacityRejectionCode.COIN_METADATA_LAYOUT_MISMATCH.value,
            "coin metadata carries bytes outside the pinned layout",
            stage="capacity_reading",
        )
    return NaviCoinMetadataState(
        coin_type=coin_type,
        decimals=decimals,
        name=text_name,
        symbol=text_symbol,
        description=text_description,
        icon_url=icon_url,
    )


@dataclass(frozen=True, slots=True)
class NaviFlashloanApiDiscoveryRow:
    """Demoted getAllFlashLoanAssets row: DISCOVERY, never on-chain capacity.

    The row is intentionally incapable of producing capital rows: the only
    conversion entry point raises NAVI_API_ONLY_NOT_ONCHAIN forever.
    """

    coin_type: str
    max_decimal: str
    min_decimal: str
    flashloan_fee: Fraction
    asset_id: int
    pool_id: str
    evidence_state: NaviCapacityEvidenceState = (
        NaviCapacityEvidenceState.DISCOVERY_ONLY_OFFCHAIN_API
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "coin_type", _full_coin_type(self.coin_type, "coin_type")
        )
        _decimal_string(self.max_decimal, "max")
        _decimal_string(self.min_decimal, "min")
        if not isinstance(self.flashloan_fee, Fraction) or not (
            0 <= self.flashloan_fee < 1
        ):
            raise MultiChainError(
                NaviCapacityRejectionCode.API_DISCOVERY_ROW_SCHEMA_DRIFT.value,
                "flashloan fee must be an exact rational in [0, 1)",
                stage="capacity_reading",
            )
        if type(self.asset_id) is not int or self.asset_id < 0:
            raise MultiChainError(
                NaviCapacityRejectionCode.API_DISCOVERY_ROW_SCHEMA_DRIFT.value,
                "asset id must be a non-negative integer",
                stage="capacity_reading",
            )
        object.__setattr__(self, "pool_id", _object_id(self.pool_id, "pool_id"))
        if self.evidence_state is not (
            NaviCapacityEvidenceState.DISCOVERY_ONLY_OFFCHAIN_API
        ):
            raise MultiChainError(
                NaviCapacityRejectionCode.API_DISCOVERY_NOT_ONCHAIN.value,
                "API rows can only carry the discovery-only evidence state",
                stage="capacity_reading",
            )

    def capital_rows(self, decimals_by_type: dict[str, int]) -> None:
        """Structural demotion: never produces capital rows, proven or not."""

        raise MultiChainError(
            NaviCapacityRejectionCode.API_DISCOVERY_NOT_ONCHAIN.value,
            "getAllFlashLoanAssets is off-chain API discovery and never an "
            "on-chain capacity proof",
            stage="capacity_reading",
        )


def parse_flashloan_api_discovery_rows(
    rows: list[dict],
) -> tuple[NaviFlashloanApiDiscoveryRow, ...]:
    """Parse and demote getAllFlashLoanAssets-shaped rows, fail-closed.

    The off-chain API returns JS numbers for ``flashloanFee``; the SDK bridge
    must hand over exact decimal strings, because any float input is rejected
    as precision loss rather than coerced.
    """

    if not isinstance(rows, list) or len(rows) > NAVI_MAX_DISCOVERY_ROWS:
        raise MultiChainError(
            NaviCapacityRejectionCode.API_DISCOVERY_ROW_SCHEMA_DRIFT.value,
            "discovery rows must be a list within the result cap",
            stage="capacity_reading",
        )
    result: list[NaviFlashloanApiDiscoveryRow] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise MultiChainError(
                NaviCapacityRejectionCode.API_DISCOVERY_ROW_SCHEMA_DRIFT.value,
                "discovery row must be an object",
                stage="capacity_reading",
            )
        coin_type = _full_coin_type(row.get("coinType"), "coinType")
        max_decimal = _decimal_string(row.get("max"), "max")
        min_decimal = _decimal_string(row.get("min"), "min")
        fee = Fraction(_decimal_string(row.get("flashloanFee"), "flashloanFee"))
        asset_id = row.get("assetId")
        pool_id = row.get("poolId")
        if type(asset_id) is not int or asset_id < 0:
            raise MultiChainError(
                NaviCapacityRejectionCode.API_DISCOVERY_ROW_SCHEMA_DRIFT.value,
                "assetId must be a non-negative integer",
                stage="capacity_reading",
            )
        if not isinstance(pool_id, str):
            raise MultiChainError(
                NaviCapacityRejectionCode.API_DISCOVERY_ROW_SCHEMA_DRIFT.value,
                "poolId must be a 0x object id string",
                stage="capacity_reading",
            )
        if coin_type in seen:
            raise MultiChainError(
                NaviCapacityRejectionCode.API_DISCOVERY_ROW_SCHEMA_DRIFT.value,
                "duplicate discovery row for one coin type",
                stage="capacity_reading",
            )
        seen.add(coin_type)
        result.append(
            NaviFlashloanApiDiscoveryRow(
                coin_type=coin_type,
                max_decimal=max_decimal,
                min_decimal=min_decimal,
                flashloan_fee=fee,
                asset_id=asset_id,
                pool_id=pool_id,
            )
        )
    return tuple(result)


@dataclass(frozen=True, slots=True)
class NaviFlashPtbStep:
    """One pinned PTB moveCall shape. Static knowledge, never executable."""

    function: str
    package_id: str
    arguments: tuple[str, ...]
    type_arguments: tuple[str, ...]
    produces_hot_potato: tuple[str, ...]
    consumes_hot_potato: tuple[str, ...]


def navi_flash_ptb_shape(
    version: int,
    *,
    package_id: str,
    coin_type: str,
) -> tuple[NaviFlashPtbStep, ...]:
    """Pinned v1/v2 flash borrow/repay moveCall shapes (R03 knowledge).

    Mirrors the vendored @naviprotocol/lending@2.0.12 helper exactly:
    version 1 -> lending::flash_loan_with_ctx, version 2 ->
    lending::flash_loan_with_ctx_v2 with the extra 0x05 SuiSystemState
    dependency; repayment is lending::flash_repay_with_ctx with the 0x06
    Clock, storage, pool, receipt and coin. The receipt hot potato must be
    consumed in the same PTB. No signing/sending happens or is possible here.
    """

    package = _object_id(package_id, "package_id")
    coin = _full_coin_type(coin_type, "coin_type")
    if version == 1:
        borrow_args: tuple[str, ...] = ("flashloan_config", "pool", "amount:u64")
    elif version == 2:
        borrow_args = (
            "flashloan_config",
            "pool",
            "amount:u64",
            NAVI_SUI_SYSTEM_STATE_ID,
        )
    else:
        raise MultiChainError(
            NaviCapacityRejectionCode.PACKAGE_VERSION_UNKNOWN.value,
            "flash PTB shape is pinned only for config versions 1 and 2",
            stage="capacity_reading",
        )
    steps = (
        NaviFlashPtbStep(
            function=NAVI_FLASH_ENTRY_V1 if version == 1 else NAVI_FLASH_ENTRY_V2,
            package_id=package,
            arguments=borrow_args,
            type_arguments=(coin,),
            produces_hot_potato=("receipt",),
            consumes_hot_potato=(),
        ),
        NaviFlashPtbStep(
            function=NAVI_FLASH_REPAY_ENTRY,
            package_id=package,
            arguments=(NAVI_CLOCK_ID, "storage", "pool", "receipt", "coin"),
            type_arguments=(coin,),
            produces_hot_potato=(),
            consumes_hot_potato=("receipt",),
        ),
    )
    produced = {step.function: step.produces_hot_potato for step in steps}
    consumed = {step.function: step.consumes_hot_potato for step in steps}
    open_potatoes: set[str] = set()
    for step in steps:
        open_potatoes |= set(step.produces_hot_potato)
        open_potatoes -= set(step.consumes_hot_potato)
    if open_potatoes:
        raise MultiChainError(
            "SUI_HOT_POTATO_NOT_CLOSED",
            f"pinned shape leaves an open hot potato: {sorted(open_potatoes)} "
            f"produced={produced} consumed={consumed}",
            stage="settlement",
        )
    return steps


@dataclass(frozen=True, slots=True)
class NaviPoolCapacityObservation:
    """Typed read-only NAVI pool capacity observation from captured state.

    ``raw_pool_resource_fields`` are raw values captured from actual pool
    object content; their Move semantics are unpinned, so they are recorded
    with UNAUDITED_SEMANTICS and are never capacity. ``effective_capacity_
    units`` stays ``None`` while the derivation is UNPROVEN: unknown is not
    zero.
    """

    package_id: str
    package_version: int
    pool_capture: NaviObjectCapture
    market_config: NaviMarketConfigCapture
    checkpoint_binding: NaviSuiCheckpointBinding
    coin_type: str
    coin_decimals: int | None
    coin_metadata: NaviCoinMetadataState | None
    flashloan_config_capture: NaviObjectCapture | None
    raw_pool_resource_fields: tuple[tuple[str, str], ...]
    raw_resource_semantics: str
    capacity_derivation: NaviCapacityDerivation
    effective_capacity_units: int | None
    constraint_gaps: tuple[str, ...]
    blockers: tuple[str, ...]
    api_discovery_rows: tuple[NaviFlashloanApiDiscoveryRow, ...]
    object_bindings: tuple[tuple[str, int, str], ...]
    evidence_state: NaviCapacityEvidenceState
    transport: NaviSuiReadTransport
    decoder_identity: str = NAVI_READER_DECODER_IDENTITY
    decoder_generation: int = NAVI_READER_DECODER_GENERATION
    execution_authority: str = NAVI_READER_EXECUTION_AUTHORITY
    sign_enabled: bool = False
    send_enabled: bool = False
    raw_resource_semantics_marker: str = dataclass_field(
        default="UNAUDITED_SEMANTICS_NOT_CAPACITY"
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "package_id", _object_id(self.package_id, "package_id")
        )
        object.__setattr__(
            self, "coin_type", _full_coin_type(self.coin_type, "coin_type")
        )
        if self.capacity_derivation is NaviCapacityDerivation.UNPROVEN:
            if self.effective_capacity_units is not None:
                raise MultiChainError(
                    "SUI_CAPACITY_DERIVATION_FORBIDDEN",
                    "effective capacity without proven derivation is forbidden; "
                    "unknown is not zero",
                    stage="capacity_reading",
                )
            if (
                NaviCapacityRejectionCode.MISSING_EFFECTIVE_FLASH_CAP.value
                not in self.blockers
            ):
                raise MultiChainError(
                    "SUI_UNPROVEN_CAPACITY_BLOCKER_REQUIRED",
                    "unproven capacity must carry MISSING_EFFECTIVE_FLASH_CAP",
                    stage="capacity_reading",
                )
            if not self.constraint_gaps:
                raise MultiChainError(
                    "SUI_UNPROVEN_CAPACITY_GAPS_REQUIRED",
                    "unproven capacity must enumerate constraint gaps",
                    stage="capacity_reading",
                )
        if (
            self.evidence_state
            is not NaviCapacityEvidenceState.OFFLINE_FIXTURE_NOT_ROOTED
        ):
            raise MultiChainError(
                "SUI_EVIDENCE_STATE_FORBIDDEN",
                "only offline fixture evidence can be constructed in this wave",
                stage="capacity_reading",
            )
        if self.transport is not NaviSuiReadTransport.OFFLINE_FIXTURE_CAPTURE:
            raise MultiChainError(
                "SUI_TRANSPORT_NOT_OFFLINE",
                "offline observations can only use the offline fixture transport",
                stage="capacity_reading",
            )
        if NaviCapacityRejectionCode.LIVE_SUI_CHECKPOINT_NOT_AUTHORIZED.value not in (
            self.blockers
        ):
            raise MultiChainError(
                "SUI_LIVE_CHECKPOINT_BLOCKER_REQUIRED",
                "offline observation must carry LIVE_SUI_CHECKPOINT_NOT_AUTHORIZED",
                stage="capacity_reading",
            )
        binding = self.checkpoint_binding
        for capture in (
            self.pool_capture,
            self.market_config.storage,
            self.market_config.flashloan_config,
            self.flashloan_config_capture,
        ):
            if capture is None:
                continue
            if (
                capture.checkpoint != binding.checkpoint
                or capture.epoch != binding.epoch
            ):
                raise MultiChainError(
                    NaviCapacityRejectionCode.CHECKPOINT_MISMATCH.value,
                    "object capture is bound to another checkpoint/epoch than "
                    "the recorded capture context",
                    stage="capacity_reading",
                )
        if self.pool_capture.owner_kind is not SuiObjectKind.SHARED:
            raise MultiChainError(
                NaviCapacityRejectionCode.SHARED_OBJECT_OWNER_MISMATCH.value,
                "NAVI pool object must be shared",
                stage="capacity_reading",
            )
        pool_address, _, _, pool_params = _split_type_tag(self.pool_capture.type_tag)
        if pool_address != self.market_config.package:
            raise MultiChainError(
                NaviCapacityRejectionCode.PACKAGE_ID_MISMATCH.value,
                "pool object type package differs from the captured market "
                "config package",
                stage="capacity_reading",
            )
        if len(pool_params) != 1:
            raise MultiChainError(
                NaviCapacityRejectionCode.POOL_OBJECT_TYPE_MISMATCH.value,
                "pool object type must bind exactly one coin type parameter",
                stage="capacity_reading",
            )
        pool_coin = _full_coin_type(pool_params[0], "pool_type_parameter")
        if pool_coin != self.coin_type:
            raise MultiChainError(
                NaviCapacityRejectionCode.COIN_TYPE_MISMATCH.value,
                "reviewed coin type differs from the pool object type binding",
                stage="capacity_reading",
            )
        if self.coin_metadata is not None:
            if self.coin_metadata.coin_type != self.coin_type:
                raise MultiChainError(
                    NaviCapacityRejectionCode.COIN_TYPE_MISMATCH.value,
                    "coin metadata binds another coin type than the pool",
                    stage="capacity_reading",
                )
            if self.coin_decimals != self.coin_metadata.decimals:
                raise MultiChainError(
                    NaviCapacityRejectionCode.COIN_METADATA_LAYOUT_MISMATCH.value,
                    "coin decimals differ from the decoded metadata",
                    stage="capacity_reading",
                )
        elif self.coin_decimals is not None:
            raise MultiChainError(
                NaviCapacityRejectionCode.COIN_DECIMALS_UNPROVEN.value,
                "decimals require a decoded coin metadata capture",
                stage="capacity_reading",
            )
        object_bindings = [
            (
                self.pool_capture.object_id,
                self.pool_capture.version,
                self.pool_capture.digest,
            ),
            (
                self.market_config.storage.object_id,
                self.market_config.storage.version,
                self.market_config.storage.digest,
            ),
            (
                self.market_config.flashloan_config.object_id,
                self.market_config.flashloan_config.version,
                self.market_config.flashloan_config.digest,
            ),
        ]
        if self.flashloan_config_capture is not None:
            object_bindings.append(
                (
                    self.flashloan_config_capture.object_id,
                    self.flashloan_config_capture.version,
                    self.flashloan_config_capture.digest,
                )
            )
        expected = tuple(sorted(object_bindings))
        if tuple(sorted(self.object_bindings)) != expected:
            raise MultiChainError(
                NaviCapacityRejectionCode.OBJECT_VERSION_BINDING_MISSING.value,
                "object bindings must mirror the captured objects exactly",
                stage="capacity_reading",
            )
        expected_gaps = {
            NaviCapacityRejectionCode.POOL_MOVE_LAYOUT_UNPINNED.value,
            NaviCapacityRejectionCode.FEE_CONFIG_LAYOUT_UNPINNED.value,
            NaviCapacityRejectionCode.FLASH_LIMIT_ONCHAIN_UNPINNED.value,
            NaviCapacityRejectionCode.API_DISCOVERY_NOT_ONCHAIN.value,
            "CHAIN_CHECKPOINT_IS_NOT_NAVI_POOL_STATE",
        }
        if self.coin_decimals is None:
            expected_gaps.add(NaviCapacityRejectionCode.COIN_DECIMALS_UNPROVEN.value)
        if set(self.constraint_gaps) != expected_gaps:
            raise MultiChainError(
                "SUI_CONSTRAINT_GAPS_INVALID",
                "constraint gaps must enumerate the exact unpinned set",
                stage="capacity_reading",
            )
        if self.status not in ("PARTIAL_DECODED", "BLOCKED_LIVE_STATE"):
            raise MultiChainError(
                "SUI_OBSERVATION_STATUS_INVALID",
                "unknown observation status",
                stage="capacity_reading",
            )

    @property
    def status(self) -> str:
        return "BLOCKED_LIVE_STATE" if self.blockers else "PARTIAL_DECODED"

    @property
    def evidence_digest(self) -> str:
        return hashlib.sha256(_navi_canonical_json(self).encode("utf-8")).hexdigest()

    def evidence_record(self) -> dict:
        return {
            "decoder_identity": self.decoder_identity,
            "decoder_generation": self.decoder_generation,
            "evidence_sha256": self.evidence_digest,
            "status": self.status,
            "observation": json.loads(_navi_canonical_json(self)),
        }


def _navi_canonical_json(value: object) -> str:
    def normalize(node: object) -> object:
        if is_dataclass(node) and not isinstance(node, type):
            return {
                item.name: normalize(getattr(node, item.name))
                for item in dataclass_fields(node)
            }
        if isinstance(node, StrEnum):
            return str(node.value)
        if isinstance(node, Fraction):
            return f"{node.numerator}/{node.denominator}"
        if isinstance(node, (tuple, list)):
            return [normalize(item) for item in node]
        if isinstance(node, dict):
            return {key: normalize(item) for key, item in node.items()}
        return node

    return json.dumps(
        normalize(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def observe_navi_pool_capacity(
    *,
    checkpoint_binding: NaviSuiCheckpointBinding,
    market_config: NaviMarketConfigCapture,
    pool_capture: NaviObjectCapture,
    reviewed_coin_type: str,
    coin_metadata_bytes: bytes | None = None,
    coin_metadata_type_tag: str | None = None,
    coin_metadata_owner_kind: SuiObjectKind | None = None,
    flashloan_config_capture: NaviObjectCapture | None = None,
    api_discovery_rows: list[dict] | tuple[NaviFlashloanApiDiscoveryRow, ...] = (),
    transport: NaviSuiReadTransport = NaviSuiReadTransport.OFFLINE_FIXTURE_CAPTURE,
) -> NaviPoolCapacityObservation:
    """Compose a fail-closed offline NAVI pool capacity observation.

    Every input is caller-supplied (offline fixture or, in a later authorized
    wave, a governed gRPC/GraphQL capture). No network, no signing, no PTB
    execution. Sui legacy JSON-RPC is rejected outright; governed live
    transports are typed BLOCKED because no live checkpoint read is
    authorized in this wave.
    """

    if transport is NaviSuiReadTransport.SUI_JSONRPC:
        raise MultiChainError(
            NaviCapacityRejectionCode.JSONRPC_TRANSPORT_FORBIDDEN.value,
            "Sui legacy JSON-RPC was retired and is never an allowed fallback",
            stage="capacity_reading",
        )
    if transport in (
        NaviSuiReadTransport.GOVERNED_GRPC,
        NaviSuiReadTransport.GOVERNED_GRAPHQL,
    ):
        raise MultiChainError(
            NaviCapacityRejectionCode.LIVE_SUI_CHECKPOINT_NOT_AUTHORIZED.value,
            "governed gRPC/GraphQL live checkpoint reads are not authorized in "
            "this wave; offline fixture captures only",
            stage="authorization",
        )
    if transport is not NaviSuiReadTransport.OFFLINE_FIXTURE_CAPTURE:
        raise MultiChainError(
            "SUI_TRANSPORT_UNKNOWN",
            "unknown Sui read transport",
            stage="capacity_reading",
        )
    coin_type = _full_coin_type(reviewed_coin_type, "reviewed_coin_type")
    coin_metadata: NaviCoinMetadataState | None = None
    coin_decimals: int | None = None
    if coin_metadata_bytes is not None or coin_metadata_type_tag is not None:
        if (
            coin_metadata_bytes is None
            or coin_metadata_type_tag is None
            or (coin_metadata_owner_kind is None)
        ):
            raise MultiChainError(
                NaviCapacityRejectionCode.COIN_METADATA_LAYOUT_MISMATCH.value,
                "coin metadata capture requires bytes, type tag and owner kind",
                stage="capacity_reading",
            )
        coin_metadata = decode_navi_coin_metadata(
            coin_metadata_bytes,
            type_tag=coin_metadata_type_tag,
            owner_kind=coin_metadata_owner_kind,
            expected_coin_type=coin_type,
        )
        coin_decimals = coin_metadata.decimals
    if isinstance(api_discovery_rows, list):
        demoted_rows = parse_flashloan_api_discovery_rows(api_discovery_rows)
    else:
        demoted_rows = tuple(api_discovery_rows)
    raw_fields = tuple(pool_capture.fields_raw)
    gaps = [
        NaviCapacityRejectionCode.POOL_MOVE_LAYOUT_UNPINNED.value,
        NaviCapacityRejectionCode.FEE_CONFIG_LAYOUT_UNPINNED.value,
        NaviCapacityRejectionCode.FLASH_LIMIT_ONCHAIN_UNPINNED.value,
        NaviCapacityRejectionCode.API_DISCOVERY_NOT_ONCHAIN.value,
        "CHAIN_CHECKPOINT_IS_NOT_NAVI_POOL_STATE",
    ]
    if coin_decimals is None:
        gaps.append(NaviCapacityRejectionCode.COIN_DECIMALS_UNPROVEN.value)
    blockers = [
        NaviCapacityRejectionCode.MISSING_EFFECTIVE_FLASH_CAP.value,
        NaviCapacityRejectionCode.LIVE_SUI_CHECKPOINT_NOT_AUTHORIZED.value,
    ]
    object_bindings = [
        (pool_capture.object_id, pool_capture.version, pool_capture.digest),
        (
            market_config.storage.object_id,
            market_config.storage.version,
            market_config.storage.digest,
        ),
        (
            market_config.flashloan_config.object_id,
            market_config.flashloan_config.version,
            market_config.flashloan_config.digest,
        ),
    ]
    if flashloan_config_capture is not None:
        object_bindings.append(
            (
                flashloan_config_capture.object_id,
                flashloan_config_capture.version,
                flashloan_config_capture.digest,
            )
        )
    return NaviPoolCapacityObservation(
        package_id=market_config.package,
        package_version=market_config.version,
        pool_capture=pool_capture,
        market_config=market_config,
        checkpoint_binding=checkpoint_binding,
        coin_type=coin_type,
        coin_decimals=coin_decimals,
        coin_metadata=coin_metadata,
        flashloan_config_capture=flashloan_config_capture,
        raw_pool_resource_fields=raw_fields,
        raw_resource_semantics=(
            "UNAUDITED_SEMANTICS_NOT_CAPACITY"
            if raw_fields
            else "NO_RAW_FIELDS_CAPTURED"
        ),
        capacity_derivation=NaviCapacityDerivation.UNPROVEN,
        effective_capacity_units=None,
        constraint_gaps=tuple(sorted(gaps)),
        blockers=tuple(sorted(blockers)),
        api_discovery_rows=demoted_rows,
        object_bindings=tuple(sorted(object_bindings)),
        evidence_state=NaviCapacityEvidenceState.OFFLINE_FIXTURE_NOT_ROOTED,
        transport=transport,
    )


@dataclass(frozen=True, slots=True)
class NaviCapitalEdgeGate:
    """Capacity-edge emission verdict; ``edge`` is None until fully proven."""

    edge: None
    blocker: str
    blockers: tuple[str, ...]
    note: str


def navi_capital_edge_gate(
    observation: NaviPoolCapacityObservation,
) -> NaviCapitalEdgeGate:
    """Gate edge emission behind a governed live checkpoint read and the
    frozen graph owner.

    The FlashCapitalGraph whitelist is frozen this wave; positive edges
    require governed gRPC/GraphQL checkpoint-consistent live NAVI pool object
    reads with independent quorum and audited deployed-source math. Offline
    fixture evidence never qualifies an edge.
    """

    if NaviCapacityRejectionCode.LIVE_SUI_CHECKPOINT_NOT_AUTHORIZED.value in (
        observation.blockers
    ):
        return NaviCapitalEdgeGate(
            edge=None,
            blocker=NaviCapacityRejectionCode.LIVE_SUI_CHECKPOINT_NOT_AUTHORIZED.value,
            blockers=observation.blockers,
            note=(
                "no governed gRPC/GraphQL checkpoint-consistent live NAVI pool "
                "read with independent quorum was authorized; offline fixture "
                "evidence never qualifies an edge"
            ),
        )
    if observation.effective_capacity_units is None:
        return NaviCapitalEdgeGate(
            edge=None,
            blocker=NaviCapacityRejectionCode.MISSING_EFFECTIVE_FLASH_CAP.value,
            blockers=observation.blockers,
            note="effective flash borrow cap is unknown, not zero",
        )
    return NaviCapitalEdgeGate(
        edge=None,
        blocker=NaviCapacityRejectionCode.GRAPH_ALLOWANCE_PENDING.value,
        blockers=observation.blockers,
        note=(
            "FlashCapitalGraph allowance for navi requires full evidence and "
            "independent quorum; graph owner is frozen"
        ),
    )
