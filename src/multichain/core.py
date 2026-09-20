"""AGG-11 chain-dialect contracts for default-off EVM and Sui expansion."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from importlib import resources
import json
from typing import Any, Mapping


REGISTRY_SCHEMA = "agg11.chain-capabilities.v1"


class MultiChainError(ValueError):
    """Typed fail-closed error used at AGG-11 boundaries."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        stage: str = "validation",
        retryable: bool = False,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.stage = stage
        self.retryable = retryable


class ChainDialect(StrEnum):
    SOLANA = "solana"
    EVM = "evm"
    SUI = "sui"


class CapabilityStatus(StrEnum):
    UNAVAILABLE = "unavailable"
    RESEARCH = "research"
    IMPLEMENTED_OFFLINE = "implemented_offline"
    EXTERNALLY_QUALIFIED = "externally_qualified_for_profile"
    REVOKED = "revoked"


class Effect(StrEnum):
    LOCAL_BUILD_TEST = "local_build_test"
    READ_NETWORK = "read_network"
    SIMULATE_NETWORK = "simulate_network"
    SIGN = "sign"
    SEND = "send"


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MultiChainError("TEXT_REQUIRED", f"{field} must be non-empty text")
    return value.strip()


def _uint(value: object, field: str, bits: int = 256) -> int:
    if type(value) is not int or not 0 <= value < (1 << bits):
        raise MultiChainError("UNSIGNED_INTEGER_INVALID", f"{field} must fit u{bits}")
    return value


def _hex(value: object, field: str, size: int | None = None) -> str:
    text = _text(value, field).lower()
    if not text.startswith("0x"):
        raise MultiChainError("HEX_REQUIRED", f"{field} must use 0x prefix")
    body = text[2:]
    if not body or any(char not in "0123456789abcdef" for char in body):
        raise MultiChainError("HEX_INVALID", f"{field} must be lowercase hex")
    if size is not None and len(body) != size * 2:
        raise MultiChainError("HEX_SIZE_INVALID", f"{field} has wrong byte length")
    return text


def _digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ChainIdentity:
    chain_key: str
    dialect: ChainDialect
    network_id: str
    native_asset: str
    atomic_boundary: str
    finality_model: str
    genesis_fingerprint: str | None = None
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "chain_key",
            "network_id",
            "native_asset",
            "atomic_boundary",
            "finality_model",
        ):
            _text(getattr(self, name), name)
        object.__setattr__(self, "blockers", tuple(dict.fromkeys(self.blockers)))

    @property
    def operationally_pinned(self) -> bool:
        return self.genesis_fingerprint is not None and not self.blockers


@dataclass(frozen=True, slots=True)
class DeploymentRef:
    protocol: str
    chain_key: str
    deployment_id: str
    version: str
    interface_digest: str
    artifact_digest: str
    generation: str

    def __post_init__(self) -> None:
        for name in (
            "protocol",
            "chain_key",
            "deployment_id",
            "version",
            "generation",
        ):
            _text(getattr(self, name), name)
        for name in ("interface_digest", "artifact_digest"):
            value = _text(getattr(self, name), name)
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise MultiChainError("DIGEST_INVALID", f"{name} must be sha256 hex")


@dataclass(frozen=True, slots=True)
class AssetRef:
    chain_key: str
    asset_id: str
    atomic_unit: str
    decimals: int
    generation: str

    def __post_init__(self) -> None:
        for name in ("chain_key", "asset_id", "atomic_unit", "generation"):
            _text(getattr(self, name), name)
        if type(self.decimals) is not int or not 0 <= self.decimals <= 255:
            raise MultiChainError("ASSET_DECIMALS_INVALID", "decimals must fit u8")


@dataclass(frozen=True, slots=True)
class ExactAssetAmount:
    asset: AssetRef
    units: int

    def __post_init__(self) -> None:
        if not isinstance(self.asset, AssetRef):
            raise MultiChainError("ASSET_REQUIRED", "amount needs an AssetRef")
        _uint(self.units, "units")

    def checked_add(self, other: "ExactAssetAmount") -> "ExactAssetAmount":
        if not isinstance(other, ExactAssetAmount) or other.asset != self.asset:
            raise MultiChainError("ASSET_IDENTITY_MISMATCH", "amount assets differ")
        return ExactAssetAmount(self.asset, self.units + other.units)


@dataclass(frozen=True, slots=True)
class ChainCapability:
    capability_id: str
    protocol: str
    chain_key: str
    dialect: ChainDialect
    status: CapabilityStatus
    blockers: tuple[str, ...]
    allowed_effects: tuple[Effect, ...]
    deployment: DeploymentRef | None = None

    @property
    def externally_executable(self) -> bool:
        return (
            self.status is CapabilityStatus.EXTERNALLY_QUALIFIED
            and self.deployment is not None
            and not self.blockers
            and Effect.SEND in self.allowed_effects
        )


class ChainCapabilityRegistry:
    """Immutable chain/capability registry with effect admission."""

    def __init__(
        self,
        chains: tuple[ChainIdentity, ...],
        capabilities: tuple[ChainCapability, ...],
    ) -> None:
        if len({item.chain_key for item in chains}) != len(chains):
            raise MultiChainError("DUPLICATE_CHAIN", "chain keys must be unique")
        if len({item.capability_id for item in capabilities}) != len(capabilities):
            raise MultiChainError(
                "DUPLICATE_CAPABILITY",
                "capability ids must be unique",
            )
        known = {item.chain_key: item for item in chains}
        for capability in capabilities:
            chain = known.get(capability.chain_key)
            if chain is None or chain.dialect is not capability.dialect:
                raise MultiChainError(
                    "CAPABILITY_CHAIN_MISMATCH",
                    "capability chain/dialect mismatch",
                )
        self.chains = chains
        self.capabilities = capabilities
        self._chain = known
        self._capability = {item.capability_id: item for item in capabilities}

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ChainCapabilityRegistry":
        if raw.get("schema_version") != REGISTRY_SCHEMA:
            raise MultiChainError("REGISTRY_SCHEMA_INVALID", "unsupported schema")
        chains = tuple(
            ChainIdentity(
                chain_key=_text(item.get("chain_key"), "chain_key"),
                dialect=ChainDialect(str(item.get("dialect"))),
                network_id=_text(item.get("network_id"), "network_id"),
                native_asset=_text(item.get("native_asset"), "native_asset"),
                atomic_boundary=_text(
                    item.get("atomic_boundary"),
                    "atomic_boundary",
                ),
                finality_model=_text(item.get("finality_model"), "finality_model"),
                genesis_fingerprint=item.get("genesis_fingerprint"),
                blockers=tuple(item.get("blockers", ())),
            )
            for item in raw.get("chains", ())
        )
        capabilities: list[ChainCapability] = []
        for item in raw.get("capabilities", ()):
            deployment_raw = item.get("deployment")
            deployment = None
            if deployment_raw is not None:
                deployment = DeploymentRef(
                    protocol=_text(deployment_raw.get("protocol"), "protocol"),
                    chain_key=_text(deployment_raw.get("chain_key"), "chain_key"),
                    deployment_id=_text(
                        deployment_raw.get("deployment_id"),
                        "deployment_id",
                    ),
                    version=_text(deployment_raw.get("version"), "version"),
                    interface_digest=_text(
                        deployment_raw.get("interface_digest"),
                        "interface_digest",
                    ),
                    artifact_digest=_text(
                        deployment_raw.get("artifact_digest"),
                        "artifact_digest",
                    ),
                    generation=_text(
                        deployment_raw.get("generation"),
                        "generation",
                    ),
                )
            capabilities.append(
                ChainCapability(
                    capability_id=_text(item.get("capability_id"), "capability_id"),
                    protocol=_text(item.get("protocol"), "protocol"),
                    chain_key=_text(item.get("chain_key"), "chain_key"),
                    dialect=ChainDialect(str(item.get("dialect"))),
                    status=CapabilityStatus(str(item.get("status"))),
                    blockers=tuple(item.get("blockers", ())),
                    allowed_effects=tuple(
                        Effect(str(effect))
                        for effect in item.get("allowed_effects", ())
                    ),
                    deployment=deployment,
                )
            )
        if not chains or not capabilities:
            raise MultiChainError("REGISTRY_EMPTY", "registry cannot be empty")
        return cls(chains, tuple(capabilities))

    @classmethod
    def packaged(cls) -> "ChainCapabilityRegistry":
        resource = resources.files("src.resources").joinpath(
            "multichain_capabilities.json"
        )
        return cls.from_mapping(json.loads(resource.read_text(encoding="utf-8")))

    def chain(self, chain_key: str) -> ChainIdentity:
        try:
            return self._chain[chain_key]
        except KeyError as exc:
            raise MultiChainError("CHAIN_UNKNOWN", chain_key) from exc

    def capability(self, capability_id: str) -> ChainCapability:
        try:
            return self._capability[capability_id]
        except KeyError as exc:
            raise MultiChainError("CAPABILITY_UNKNOWN", capability_id) from exc

    def require_effect(self, capability_id: str, effect: Effect) -> ChainCapability:
        capability = self.capability(capability_id)
        if effect not in capability.allowed_effects:
            raise MultiChainError(
                "EFFECT_NOT_ALLOWED",
                f"{effect.value} is not allowed",
                stage="authorization",
            )
        if effect in {Effect.SIGN, Effect.SEND} and not capability.externally_executable:
            raise MultiChainError(
                "CAPABILITY_NOT_OPERATIONALLY_QUALIFIED",
                f"{capability_id} remains default-off",
                stage="authorization",
            )
        return capability

    @property
    def digest(self) -> str:
        return _digest(
            {
                "chains": [
                    (
                        item.chain_key,
                        item.dialect.value,
                        item.network_id,
                        item.genesis_fingerprint,
                        list(item.blockers),
                    )
                    for item in self.chains
                ],
                "capabilities": [
                    (
                        item.capability_id,
                        item.status.value,
                        list(item.blockers),
                        [effect.value for effect in item.allowed_effects],
                    )
                    for item in self.capabilities
                ],
            }
        )


class EvmFinality(StrEnum):
    HEAD = "head"
    SAFE = "safe"
    FINALIZED = "finalized"


@dataclass(frozen=True, slots=True)
class EvmBlockRef:
    chain_id: int
    number: int
    block_hash: str
    parent_hash: str
    finality: EvmFinality

    def __post_init__(self) -> None:
        _uint(self.chain_id, "chain_id", bits=64)
        _uint(self.number, "number", bits=64)
        _hex(self.block_hash, "block_hash", 32)
        _hex(self.parent_hash, "parent_hash", 32)


@dataclass(frozen=True, slots=True)
class EvmStateFrame:
    chain_key: str
    block: EvmBlockRef
    deployment: DeploymentRef
    interface_digest: str
    proxy_implementation: str | None
    state_digest: str

    def __post_init__(self) -> None:
        _text(self.chain_key, "chain_key")
        if self.deployment.chain_key != self.chain_key:
            raise MultiChainError(
                "DEPLOYMENT_CHAIN_MISMATCH",
                "deployment belongs to another chain",
            )
        if self.interface_digest != self.deployment.interface_digest:
            raise MultiChainError(
                "INTERFACE_DIGEST_MISMATCH",
                "state ABI/interface does not match deployment",
            )
        if self.proxy_implementation is not None:
            _hex(self.proxy_implementation, "proxy_implementation", 20)
        if len(self.state_digest) != 64:
            raise MultiChainError("STATE_DIGEST_INVALID", "state digest must be sha256")


class EvmStateAdapter:
    @staticmethod
    def admit(
        *,
        chain: ChainIdentity,
        expected_chain_id: int,
        frame: EvmStateFrame,
    ) -> EvmStateFrame:
        if chain.dialect is not ChainDialect.EVM:
            raise MultiChainError("EVM_DIALECT_REQUIRED", "chain must be EVM")
        if int(chain.network_id) != expected_chain_id:
            raise MultiChainError("CHAIN_ID_MISMATCH", "configured chain id differs")
        if frame.chain_key != chain.chain_key or frame.block.chain_id != expected_chain_id:
            raise MultiChainError("CHAIN_ID_MISMATCH", "frame belongs to another chain")
        return frame

    @staticmethod
    def reorg_reasons(before: EvmBlockRef, after: EvmBlockRef) -> tuple[str, ...]:
        reasons: list[str] = []
        if before.chain_id != after.chain_id:
            reasons.append("chain-id-changed")
        if after.number == before.number and after.block_hash != before.block_hash:
            reasons.append("same-height-hash-changed")
        if after.number == before.number + 1 and after.parent_hash != before.block_hash:
            reasons.append("parent-discontinuity")
        return tuple(reasons)


@dataclass(frozen=True, slots=True)
class EvmCall:
    target: str
    calldata: str
    value_wei: int = 0
    callback_sender: str | None = None

    def __post_init__(self) -> None:
        _hex(self.target, "target", 20)
        _hex(self.calldata, "calldata")
        _uint(self.value_wei, "value_wei")
        if self.callback_sender is not None:
            _hex(self.callback_sender, "callback_sender", 20)


@dataclass(frozen=True, slots=True)
class EvmOperationPlan:
    chain_key: str
    chain_id: int
    sender: str
    nonce: int
    state_digest: str
    calls: tuple[EvmCall, ...]
    gas_limit: int
    max_fee_per_gas: int
    max_priority_fee_per_gas: int

    def __post_init__(self) -> None:
        _text(self.chain_key, "chain_key")
        _uint(self.chain_id, "chain_id", bits=64)
        _hex(self.sender, "sender", 20)
        _uint(self.nonce, "nonce", bits=64)
        if not self.calls:
            raise MultiChainError("EVM_CALLS_REQUIRED", "plan requires calls")
        for name in (
            "gas_limit",
            "max_fee_per_gas",
            "max_priority_fee_per_gas",
        ):
            _uint(getattr(self, name), name)
        if self.max_priority_fee_per_gas > self.max_fee_per_gas:
            raise MultiChainError("EVM_FEE_INVALID", "priority fee exceeds max fee")
        if len(self.state_digest) != 64:
            raise MultiChainError("STATE_DIGEST_INVALID", "state digest must be sha256")

    @property
    def max_gas_cost_wei(self) -> int:
        return self.gas_limit * self.max_fee_per_gas

    @property
    def digest(self) -> str:
        return _digest(
            {
                "chain_key": self.chain_key,
                "chain_id": self.chain_id,
                "sender": self.sender.lower(),
                "nonce": self.nonce,
                "state_digest": self.state_digest,
                "calls": [
                    (
                        call.target.lower(),
                        call.calldata.lower(),
                        call.value_wei,
                        call.callback_sender.lower()
                        if call.callback_sender is not None
                        else None,
                    )
                    for call in self.calls
                ],
                "gas_limit": self.gas_limit,
                "max_fee_per_gas": self.max_fee_per_gas,
                "max_priority_fee_per_gas": self.max_priority_fee_per_gas,
            }
        )


@dataclass(frozen=True, slots=True)
class EvmNonceLease:
    chain_id: int
    sender: str
    nonce: int
    intent_digest: str

    def __post_init__(self) -> None:
        _uint(self.chain_id, "chain_id", bits=64)
        _hex(self.sender, "sender", 20)
        _uint(self.nonce, "nonce", bits=64)
        if len(self.intent_digest) != 64:
            raise MultiChainError("INTENT_DIGEST_INVALID", "intent must be sha256")

    def require_same_intent(self, plan: EvmOperationPlan) -> None:
        if (
            plan.chain_id != self.chain_id
            or plan.sender.lower() != self.sender.lower()
            or plan.nonce != self.nonce
        ):
            raise MultiChainError("NONCE_SCOPE_MISMATCH", "nonce lease scope differs")
        if plan.digest != self.intent_digest:
            raise MultiChainError(
                "NONCE_INTENT_CONFLICT",
                "same nonce cannot represent another economic intent",
            )


@dataclass(frozen=True, slots=True)
class EvmSimulationEvidence:
    plan_digest: str
    state_digest: str
    block_hash: str
    success: bool
    gas_used: int
    landed: bool = False

    def __post_init__(self) -> None:
        if self.landed:
            raise MultiChainError(
                "SIMULATION_NOT_LANDING_PROOF",
                "simulation cannot claim landing",
            )
        _uint(self.gas_used, "gas_used")


class EvmExecutionAdapter:
    """Sender-free EVM compiler/simulation binding."""

    @staticmethod
    def compile(
        *,
        chain: ChainIdentity,
        frame: EvmStateFrame,
        plan: EvmOperationPlan,
        nonce_lease: EvmNonceLease,
    ) -> str:
        EvmStateAdapter.admit(
            chain=chain,
            expected_chain_id=plan.chain_id,
            frame=frame,
        )
        if plan.chain_key != chain.chain_key or plan.state_digest != frame.state_digest:
            raise MultiChainError(
                "EVM_PLAN_STATE_MISMATCH",
                "plan is not bound to this state frame",
            )
        nonce_lease.require_same_intent(plan)
        return plan.digest

    @staticmethod
    def bind_simulation(
        *,
        plan: EvmOperationPlan,
        evidence: EvmSimulationEvidence,
    ) -> None:
        if evidence.plan_digest != plan.digest:
            raise MultiChainError(
                "SIMULATION_PLAN_MISMATCH",
                "simulation belongs to another plan",
            )
        if evidence.state_digest != plan.state_digest:
            raise MultiChainError(
                "SIMULATION_STATE_MISMATCH",
                "simulation used another state",
            )
