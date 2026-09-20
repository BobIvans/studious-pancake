"""AGG-11 CHAIN-03: versioned EVM net-settlement dialects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .core import AssetRef, DeploymentRef, MultiChainError


class NetSettlementDialect(StrEnum):
    BALANCER_V3 = "balancer-v3"
    UNISWAP_V4 = "uniswap-v4"
    EKUBO_EVM = "ekubo-evm"


@dataclass(frozen=True, slots=True)
class SettlementDomain:
    domain_id: str
    dialect: NetSettlementDialect
    deployment: DeploymentRef

    def __post_init__(self) -> None:
        if not self.domain_id:
            raise MultiChainError("SETTLEMENT_DOMAIN_REQUIRED", "domain id required")
        expected = {
            NetSettlementDialect.BALANCER_V3: "balancer-v3",
            NetSettlementDialect.UNISWAP_V4: "uniswap-v4",
            NetSettlementDialect.EKUBO_EVM: "ekubo-evm",
        }[self.dialect]
        if self.deployment.protocol != expected:
            raise MultiChainError(
                "SETTLEMENT_PROTOCOL_MISMATCH",
                "settlement dialect does not match deployment protocol",
            )


@dataclass(frozen=True, slots=True)
class AssetDelta:
    asset: AssetRef
    units: int

    def __post_init__(self) -> None:
        if not isinstance(self.asset, AssetRef):
            raise MultiChainError("ASSET_REQUIRED", "delta requires AssetRef")
        if type(self.units) is not int or not -(1 << 255) <= self.units < (1 << 255):
            raise MultiChainError("DELTA_RANGE_INVALID", "delta must fit i256")


@dataclass(frozen=True, slots=True)
class NetSettlementTrace:
    domain: SettlementDomain
    callback_sender: str
    deltas: tuple[AssetDelta, ...]
    unlocked: bool
    settled: bool

    @property
    def residual_by_asset(self) -> dict[AssetRef, int]:
        residual: dict[AssetRef, int] = {}
        for delta in self.deltas:
            residual[delta.asset] = residual.get(delta.asset, 0) + delta.units
        return residual


class NetSettlementAdapter:
    """Model lock/unlock/callback settlement with zero terminal liabilities."""

    def __init__(self, domain: SettlementDomain) -> None:
        self.domain = domain

    def begin(self, callback_sender: str) -> NetSettlementTrace:
        if not callback_sender:
            raise MultiChainError(
                "CALLBACK_SENDER_REQUIRED",
                "settlement callback sender required",
            )
        return NetSettlementTrace(
            domain=self.domain,
            callback_sender=callback_sender.lower(),
            deltas=(),
            unlocked=True,
            settled=False,
        )

    def apply(
        self,
        trace: NetSettlementTrace,
        *,
        domain: SettlementDomain,
        delta: AssetDelta,
    ) -> NetSettlementTrace:
        if trace.domain != self.domain or domain != self.domain:
            raise MultiChainError(
                "CROSS_SETTLEMENT_DOMAIN_FORBIDDEN",
                "liabilities cannot net across settlement domains",
            )
        if not trace.unlocked or trace.settled:
            raise MultiChainError(
                "SETTLEMENT_STATE_INVALID",
                "delta applied outside active settlement callback",
            )
        return NetSettlementTrace(
            domain=trace.domain,
            callback_sender=trace.callback_sender,
            deltas=trace.deltas + (delta,),
            unlocked=True,
            settled=False,
        )

    def finalize(self, trace: NetSettlementTrace) -> NetSettlementTrace:
        if trace.domain != self.domain:
            raise MultiChainError(
                "SETTLEMENT_DOMAIN_MISMATCH",
                "trace belongs to another settlement domain",
            )
        residual = {
            asset: units
            for asset, units in trace.residual_by_asset.items()
            if units != 0
        }
        if residual:
            raise MultiChainError(
                "SETTLEMENT_RESIDUAL_NONZERO",
                "all settlement liabilities must be zero",
                stage="settlement",
            )
        return NetSettlementTrace(
            domain=trace.domain,
            callback_sender=trace.callback_sender,
            deltas=trace.deltas,
            unlocked=False,
            settled=True,
        )


def require_same_domain(
    left: SettlementDomain,
    right: SettlementDomain,
) -> None:
    if left != right:
        raise MultiChainError(
            "CROSS_SETTLEMENT_DOMAIN_FORBIDDEN",
            "Balancer/Uniswap/Ekubo domains are not interchangeable",
        )
