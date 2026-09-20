"""AGG-11 CHAIN-02: sender-free EVM flash financing semantics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from .core import AssetRef, DeploymentRef, ExactAssetAmount, MultiChainError


def _address(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.startswith("0x"):
        raise MultiChainError("EVM_ADDRESS_INVALID", f"{field} must be 0x address")
    body = value[2:].lower()
    if len(body) != 40 or any(char not in "0123456789abcdef" for char in body):
        raise MultiChainError("EVM_ADDRESS_INVALID", f"{field} must be 20 bytes")
    return "0x" + body


def _uint(value: object, field: str) -> int:
    if type(value) is not int or not 0 <= value < (1 << 256):
        raise MultiChainError("EVM_UINT_INVALID", f"{field} must fit uint256")
    return value


def _ceil_bps(amount: int, bps: int) -> int:
    return (amount * bps + 9_999) // 10_000


@dataclass(frozen=True, slots=True)
class EvmProtocolEvidence:
    deployment: DeploymentRef
    contract_address: str
    callback_sender: str
    source_ref: str

    def __post_init__(self) -> None:
        if not self.source_ref:
            raise MultiChainError("SOURCE_REF_REQUIRED", "protocol evidence needs source")
        _address(self.contract_address, "contract_address")
        _address(self.callback_sender, "callback_sender")


@dataclass(frozen=True, slots=True)
class EvmDebt:
    principal: ExactAssetAmount
    fee_units: int
    repayment_units: int

    def __post_init__(self) -> None:
        _uint(self.fee_units, "fee_units")
        _uint(self.repayment_units, "repayment_units")
        if self.repayment_units != self.principal.units + self.fee_units:
            raise MultiChainError(
                "REPAYMENT_ARITHMETIC_MISMATCH",
                "repayment must equal principal plus fee",
            )


@dataclass(frozen=True, slots=True)
class EvmFlashObligation:
    protocol: str
    receiver: str
    expected_callback_sender: str
    debts: tuple[EvmDebt, ...]
    callback_kind: str
    deployment: DeploymentRef

    def __post_init__(self) -> None:
        _address(self.receiver, "receiver")
        _address(self.expected_callback_sender, "expected_callback_sender")
        if not self.debts:
            raise MultiChainError("DEBT_REQUIRED", "flash obligation needs debt")
        if self.deployment.protocol != self.protocol:
            raise MultiChainError(
                "PROTOCOL_DEPLOYMENT_MISMATCH",
                "obligation deployment protocol differs",
            )

    def require_callback(self, sender: str) -> None:
        if _address(sender, "callback_sender") != _address(
            self.expected_callback_sender,
            "expected_callback_sender",
        ):
            raise MultiChainError(
                "CALLBACK_SENDER_MISMATCH",
                "flash callback sender is not the qualified deployment",
                stage="callback",
            )


class AaveFlashMode(StrEnum):
    SIMPLE = "flashLoanSimple"
    MULTI = "flashLoan"


class AaveFinancingAdapter:
    """Build exact Aave debt without hard-coding premium or deployment."""

    @staticmethod
    def prepare(
        *,
        evidence: EvmProtocolEvidence,
        mode: AaveFlashMode,
        receiver: str,
        initiator: str,
        expected_initiator: str,
        principals: tuple[ExactAssetAmount, ...],
        premium_bps: int,
        reserve_caps: Mapping[str, int],
    ) -> EvmFlashObligation:
        if evidence.deployment.protocol != "aave":
            raise MultiChainError("AAVE_DEPLOYMENT_REQUIRED", "wrong deployment")
        if _address(initiator, "initiator") != _address(
            expected_initiator,
            "expected_initiator",
        ):
            raise MultiChainError("AAVE_INITIATOR_MISMATCH", "unexpected initiator")
        if mode is AaveFlashMode.SIMPLE and len(principals) != 1:
            raise MultiChainError(
                "AAVE_SIMPLE_SINGLE_ASSET_REQUIRED",
                "flashLoanSimple accepts one asset",
            )
        if not principals:
            raise MultiChainError("AAVE_PRINCIPAL_REQUIRED", "missing principal")
        _uint(premium_bps, "premium_bps")
        debts = []
        for principal in principals:
            cap = reserve_caps.get(principal.asset.asset_id)
            if cap is None or principal.units > cap:
                raise MultiChainError(
                    "AAVE_RESERVE_CAP_EXCEEDED",
                    "principal exceeds verified reserve cap",
                )
            fee = _ceil_bps(principal.units, premium_bps)
            debts.append(EvmDebt(principal, fee, principal.units + fee))
        return EvmFlashObligation(
            protocol="aave",
            receiver=receiver,
            expected_callback_sender=evidence.callback_sender,
            debts=tuple(debts),
            callback_kind=mode.value,
            deployment=evidence.deployment,
        )


class MorphoFinancingAdapter:
    """Model Morpho singleton flash liquidity and exact callback debt."""

    @staticmethod
    def prepare(
        *,
        evidence: EvmProtocolEvidence,
        receiver: str,
        principal: ExactAssetAmount,
        singleton_capacity: int,
        fee_units: int,
    ) -> EvmFlashObligation:
        if evidence.deployment.protocol != "morpho":
            raise MultiChainError("MORPHO_DEPLOYMENT_REQUIRED", "wrong deployment")
        _uint(singleton_capacity, "singleton_capacity")
        _uint(fee_units, "fee_units")
        if principal.units > singleton_capacity:
            raise MultiChainError(
                "MORPHO_CAPACITY_EXCEEDED",
                "flash principal exceeds singleton capacity",
            )
        debt = EvmDebt(
            principal,
            fee_units,
            principal.units + fee_units,
        )
        return EvmFlashObligation(
            protocol="morpho",
            receiver=receiver,
            expected_callback_sender=evidence.callback_sender,
            debts=(debt,),
            callback_kind="onMorphoFlashLoan",
            deployment=evidence.deployment,
        )


class DodoPoolKind(StrEnum):
    DVM = "DVM"
    DPP = "DPP"
    DSP = "DSP"


class DodoFinancingAdapter:
    """Track DODO base/quote debts independently; no generic fee assumption."""

    @staticmethod
    def prepare(
        *,
        evidence: EvmProtocolEvidence,
        pool_kind: DodoPoolKind,
        receiver: str,
        base_principal: ExactAssetAmount | None,
        quote_principal: ExactAssetAmount | None,
        base_fee_units: int,
        quote_fee_units: int,
        base_capacity: int,
        quote_capacity: int,
    ) -> EvmFlashObligation:
        if evidence.deployment.protocol != "dodo":
            raise MultiChainError("DODO_DEPLOYMENT_REQUIRED", "wrong deployment")
        _uint(base_fee_units, "base_fee_units")
        _uint(quote_fee_units, "quote_fee_units")
        _uint(base_capacity, "base_capacity")
        _uint(quote_capacity, "quote_capacity")
        debts: list[EvmDebt] = []
        if base_principal is not None:
            if base_principal.units > base_capacity:
                raise MultiChainError(
                    "DODO_BASE_CAPACITY_EXCEEDED",
                    "base debt exceeds pool capacity",
                )
            debts.append(
                EvmDebt(
                    base_principal,
                    base_fee_units,
                    base_principal.units + base_fee_units,
                )
            )
        if quote_principal is not None:
            if quote_principal.units > quote_capacity:
                raise MultiChainError(
                    "DODO_QUOTE_CAPACITY_EXCEEDED",
                    "quote debt exceeds pool capacity",
                )
            debts.append(
                EvmDebt(
                    quote_principal,
                    quote_fee_units,
                    quote_principal.units + quote_fee_units,
                )
            )
        if not debts:
            raise MultiChainError("DODO_DEBT_REQUIRED", "base or quote debt required")
        return EvmFlashObligation(
            protocol="dodo",
            receiver=receiver,
            expected_callback_sender=evidence.callback_sender,
            debts=tuple(debts),
            callback_kind=f"DODOFlashLoanCall:{pool_kind.value}",
            deployment=evidence.deployment,
        )


@dataclass(frozen=True, slots=True)
class FlashMintCapacity:
    max_flash_loan: int
    facilitator_remaining: int
    psm_exit_capacity: int

    def __post_init__(self) -> None:
        _uint(self.max_flash_loan, "max_flash_loan")
        _uint(self.facilitator_remaining, "facilitator_remaining")
        _uint(self.psm_exit_capacity, "psm_exit_capacity")

    @property
    def executable_capacity(self) -> int:
        return min(
            self.max_flash_loan,
            self.facilitator_remaining,
            self.psm_exit_capacity,
        )


class FlashMintAdapter:
    """ERC-3156/GHO-like flash mint with bounded facilitator and exit capacity."""

    @staticmethod
    def prepare(
        *,
        evidence: EvmProtocolEvidence,
        receiver: str,
        principal: ExactAssetAmount,
        capacity: FlashMintCapacity,
        fee_units: int,
    ) -> EvmFlashObligation:
        if evidence.deployment.protocol != "flash-mint":
            raise MultiChainError("FLASH_MINT_DEPLOYMENT_REQUIRED", "wrong deployment")
        _uint(fee_units, "fee_units")
        if principal.units > capacity.executable_capacity:
            raise MultiChainError(
                "FLASH_MINT_CAPACITY_EXCEEDED",
                "mint/bucket/exit capacity is insufficient",
            )
        debt = EvmDebt(
            principal,
            fee_units,
            principal.units + fee_units,
        )
        return EvmFlashObligation(
            protocol="flash-mint",
            receiver=receiver,
            expected_callback_sender=evidence.callback_sender,
            debts=(debt,),
            callback_kind="onFlashLoan",
            deployment=evidence.deployment,
        )


def validate_repayment(
    obligation: EvmFlashObligation,
    actual_units: Mapping[str, int],
) -> None:
    for debt in obligation.debts:
        paid = actual_units.get(debt.principal.asset.asset_id)
        if paid != debt.repayment_units:
            raise MultiChainError(
                "FLASH_REPAYMENT_MISMATCH",
                f"repayment mismatch for {debt.principal.asset.asset_id}",
                stage="settlement",
            )
