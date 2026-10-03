"""Per-asset financing qualification arithmetic; no calls to lenders."""

from dataclasses import dataclass
from .financing import FinancingEvidence, FinancingContractError


@dataclass(frozen=True, slots=True)
class ShadowFundingCapacity:
    evidence: FinancingEvidence
    domain: str
    asset_identity: str
    available_atoms: int
    fee_numerator: int
    fee_denominator: int
    protocol_rounding_atoms: int
    available_at_ns: int
    expiry_ns: int
    entitlement_verified: bool = False
    atomic_repayment_verified: bool = False

    def __post_init__(self):
        if (
            not isinstance(self.evidence, FinancingEvidence)
            or not self.domain.strip()
            or not self.asset_identity.strip()
        ):
            raise FinancingContractError("funding identity required")
        for field in (
            "available_atoms",
            "fee_numerator",
            "fee_denominator",
            "protocol_rounding_atoms",
            "available_at_ns",
            "expiry_ns",
        ):
            if type(getattr(self, field)) is not int or getattr(self, field) < 0:
                raise FinancingContractError("integer funding terms required")
        if (
            self.fee_denominator <= 0
            or self.fee_numerator >= self.fee_denominator
            or self.expiry_ns <= self.available_at_ns
        ):
            raise FinancingContractError("funding terms invalid")
        if (
            type(self.entitlement_verified) is not bool
            or type(self.atomic_repayment_verified) is not bool
        ):
            raise FinancingContractError("qualification flags require bool")

    def repayment(
        self, principal: int, *, now_ns: int, domain: str, asset_identity: str
    ) -> int:
        if type(principal) is not int or principal <= 0 or type(now_ns) is not int:
            raise FinancingContractError("integer principal and clock required")
        if (
            not self.entitlement_verified
            or not self.atomic_repayment_verified
            or (domain, asset_identity) != (self.domain, self.asset_identity)
            or not self.available_at_ns <= now_ns < self.expiry_ns
        ):
            raise FinancingContractError("funding unqualified or stale")
        if principal > self.available_atoms:
            raise FinancingContractError("funding capacity exceeded")
        return (
            principal
            + (principal * self.fee_numerator + self.fee_denominator - 1)
            // self.fee_denominator
            + self.protocol_rounding_atoms
        )


def debt_is_closed(
    *,
    outputs_by_asset: dict[str, int],
    repayments_by_asset: dict[str, int],
    native_wallet_atoms: int,
    native_cost_atoms: int,
) -> bool:
    for mapping in (outputs_by_asset, repayments_by_asset):
        if any(
            not isinstance(key, str)
            or not key.strip()
            or type(value) is not int
            or value < 0
            for key, value in mapping.items()
        ):
            raise FinancingContractError("per-asset debt vector required")
    if any(
        type(value) is not int or value < 0
        for value in (native_wallet_atoms, native_cost_atoms)
    ):
        raise FinancingContractError("native wallet costs require integer atoms")
    return native_wallet_atoms >= native_cost_atoms and all(
        outputs_by_asset.get(asset, 0) >= debt
        for asset, debt in repayments_by_asset.items()
    )
