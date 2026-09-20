"""AGG-11 CHAIN-04: Sui object/PTB and flash-liquidity semantics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

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
                    if item.object_id.lower() == _object_id(
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
