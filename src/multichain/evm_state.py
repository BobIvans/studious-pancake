"""AGG-11 NF-258/259 explicit EVM state, allowance and receipt evidence."""

from __future__ import annotations

from dataclasses import dataclass

from .core import (
    EvmOperationPlan,
    EvmStateFrame,
    MultiChainError,
)


def _address(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise MultiChainError("EVM_ADDRESS_INVALID", f"{field} must be 0x address")
    body = value[2:].lower()
    if len(body) != 40 or any(char not in "0123456789abcdef" for char in body):
        raise MultiChainError("EVM_ADDRESS_INVALID", f"{field} must be 20 bytes")
    return "0x" + body


def _hash32(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise MultiChainError("EVM_HASH_INVALID", f"{field} must be 0x hash")
    body = value[2:].lower()
    if len(body) != 64 or any(char not in "0123456789abcdef" for char in body):
        raise MultiChainError("EVM_HASH_INVALID", f"{field} must be 32 bytes")
    return "0x" + body


def _uint(value: object, field: str) -> int:
    if type(value) is not int or not 0 <= value < (1 << 256):
        raise MultiChainError("EVM_UINT_INVALID", f"{field} must fit uint256")
    return value


@dataclass(frozen=True, slots=True)
class EvmAccountState:
    address: str
    nonce: int
    balance_wei: int
    code_hash: str
    storage_digest: str

    def __post_init__(self) -> None:
        _address(self.address, "address")
        _uint(self.nonce, "nonce")
        _uint(self.balance_wei, "balance_wei")
        _hash32(self.code_hash, "code_hash")
        if len(self.storage_digest) != 64:
            raise MultiChainError(
                "STORAGE_DIGEST_INVALID",
                "storage digest must be sha256 hex",
            )


@dataclass(frozen=True, slots=True)
class EvmLogObservation:
    block_hash: str
    transaction_hash: str
    log_index: int
    address: str
    topics: tuple[str, ...]
    data: str

    def __post_init__(self) -> None:
        _hash32(self.block_hash, "block_hash")
        _hash32(self.transaction_hash, "transaction_hash")
        _uint(self.log_index, "log_index")
        _address(self.address, "address")
        for topic in self.topics:
            _hash32(topic, "topic")
        if not isinstance(self.data, str) or not self.data.startswith("0x"):
            raise MultiChainError("LOG_DATA_INVALID", "log data must be hex")


@dataclass(frozen=True, slots=True)
class EvmTraceObservation:
    call_path: tuple[int, ...]
    caller: str
    callee: str
    value_wei: int
    success: bool

    def __post_init__(self) -> None:
        for index in self.call_path:
            _uint(index, "call_path_index")
        _address(self.caller, "caller")
        _address(self.callee, "callee")
        _uint(self.value_wei, "value_wei")


@dataclass(frozen=True, slots=True)
class EvmStateSnapshot:
    frame: EvmStateFrame
    accounts: tuple[EvmAccountState, ...]
    logs: tuple[EvmLogObservation, ...] = ()
    traces: tuple[EvmTraceObservation, ...] = ()

    def __post_init__(self) -> None:
        addresses = [item.address.lower() for item in self.accounts]
        if len(addresses) != len(set(addresses)):
            raise MultiChainError(
                "EVM_DUPLICATE_ACCOUNT_STATE",
                "snapshot account identities must be unique",
            )
        block_hash = self.frame.block.block_hash.lower()
        for log in self.logs:
            if log.block_hash.lower() != block_hash:
                raise MultiChainError(
                    "EVM_LOG_BLOCK_MISMATCH",
                    "log evidence belongs to another block",
                )

    def require_account(self, address: str) -> EvmAccountState:
        normalized = _address(address, "address")
        for item in self.accounts:
            if item.address.lower() == normalized:
                return item
        raise MultiChainError(
            "EVM_ACCOUNT_STATE_MISSING",
            "required account/storage state is missing",
        )


@dataclass(frozen=True, slots=True)
class EvmAllowanceRequirement:
    token: str
    owner: str
    spender: str
    minimum_units: int

    def __post_init__(self) -> None:
        _address(self.token, "token")
        _address(self.owner, "owner")
        _address(self.spender, "spender")
        _uint(self.minimum_units, "minimum_units")


@dataclass(frozen=True, slots=True)
class EvmExecutionEnvelope:
    plan: EvmOperationPlan
    allowances: tuple[EvmAllowanceRequirement, ...]
    expected_callback_senders: tuple[str, ...]

    def __post_init__(self) -> None:
        normalized = tuple(
            _address(item, "expected_callback_sender")
            for item in self.expected_callback_senders
        )
        if len(normalized) != len(set(normalized)):
            raise MultiChainError(
                "EVM_DUPLICATE_CALLBACK_SENDER",
                "callback sender identities must be unique",
            )

    def validate_allowance(
        self,
        *,
        token: str,
        owner: str,
        spender: str,
        actual_units: int,
    ) -> None:
        normalized = (
            _address(token, "token"),
            _address(owner, "owner"),
            _address(spender, "spender"),
        )
        _uint(actual_units, "actual_units")
        for requirement in self.allowances:
            identity = (
                requirement.token.lower(),
                requirement.owner.lower(),
                requirement.spender.lower(),
            )
            if identity == normalized:
                if actual_units < requirement.minimum_units:
                    raise MultiChainError(
                        "EVM_ALLOWANCE_INSUFFICIENT",
                        "allowance is below the exact plan requirement",
                    )
                return
        raise MultiChainError(
            "EVM_ALLOWANCE_UNDECLARED",
            "allowance is not declared by the plan",
        )


@dataclass(frozen=True, slots=True)
class EvmStateDelta:
    address: str
    balance_delta_wei: int
    nonce_before: int
    nonce_after: int

    def __post_init__(self) -> None:
        _address(self.address, "address")
        if type(self.balance_delta_wei) is not int:
            raise MultiChainError(
                "EVM_BALANCE_DELTA_INVALID",
                "balance delta must be exact integer wei",
            )
        _uint(self.nonce_before, "nonce_before")
        _uint(self.nonce_after, "nonce_after")


@dataclass(frozen=True, slots=True)
class EvmExecutionReceipt:
    chain_id: int
    plan_digest: str
    transaction_hash: str
    block_hash: str
    nonce: int
    gas_used: int
    effective_gas_price: int
    fee_components_wei: tuple[int, ...]
    state_deltas: tuple[EvmStateDelta, ...]
    status_success: bool
    landed: bool

    def __post_init__(self) -> None:
        _uint(self.chain_id, "chain_id")
        if len(self.plan_digest) != 64:
            raise MultiChainError("PLAN_DIGEST_INVALID", "plan digest must be sha256")
        _hash32(self.transaction_hash, "transaction_hash")
        _hash32(self.block_hash, "block_hash")
        _uint(self.nonce, "nonce")
        _uint(self.gas_used, "gas_used")
        _uint(self.effective_gas_price, "effective_gas_price")
        for item in self.fee_components_wei:
            _uint(item, "fee_component_wei")
        if not self.landed:
            raise MultiChainError(
                "EVM_RECEIPT_NOT_LANDED",
                "execution receipt must represent a landed transaction",
            )

    @property
    def exact_fee_wei(self) -> int:
        return self.gas_used * self.effective_gas_price + sum(
            self.fee_components_wei
        )


def validate_execution_receipt(
    plan: EvmOperationPlan,
    receipt: EvmExecutionReceipt,
) -> None:
    if receipt.chain_id != plan.chain_id:
        raise MultiChainError(
            "EVM_RECEIPT_CHAIN_MISMATCH",
            "receipt belongs to another chain",
        )
    if receipt.nonce != plan.nonce:
        raise MultiChainError(
            "EVM_RECEIPT_NONCE_MISMATCH",
            "receipt belongs to another nonce",
        )
    if receipt.plan_digest != plan.digest:
        raise MultiChainError(
            "EVM_RECEIPT_PLAN_MISMATCH",
            "receipt is not bound to the exact economic intent",
        )
