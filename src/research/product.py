"""PRODUCT-01: default-off product experiment contracts and attribution ledger."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Iterable

from .common import (
    ResearchFailure,
    hash_json,
    require_id,
    require_nonnegative,
    require_positive,
    require_sha256,
    require_text,
    unique_nonempty,
)


@dataclass(frozen=True, slots=True)
class PaymasterCapability:
    provider_id: str
    capability_sha256: str
    fee_payer_funded: bool
    accepted_payment_assets: tuple[str, ...]
    max_sponsor_base_units: int
    policy_sha256: str
    externally_verified: bool

    def __post_init__(self) -> None:
        require_id(self.provider_id, "provider_id")
        require_sha256(self.capability_sha256, "capability_sha256")
        require_sha256(self.policy_sha256, "policy_sha256")
        unique_nonempty(self.accepted_payment_assets, "accepted_payment_asset")
        require_nonnegative(self.max_sponsor_base_units, "max_sponsor_base_units")


@dataclass(frozen=True, slots=True)
class SponsorBudget:
    sponsor_id: str
    fee_asset_id: str
    available_base_units: int
    reserved_base_units: int
    loss_cap_base_units: int
    per_request_cap_base_units: int

    def __post_init__(self) -> None:
        require_id(self.sponsor_id, "sponsor_id")
        require_id(self.fee_asset_id, "fee_asset_id")
        for field_name in (
            "available_base_units",
            "reserved_base_units",
            "loss_cap_base_units",
            "per_request_cap_base_units",
        ):
            require_nonnegative(getattr(self, field_name), field_name)
        if self.reserved_base_units > self.available_base_units:
            raise ValueError("reserved sponsor budget exceeds available balance")

    @property
    def free_base_units(self) -> int:
        return self.available_base_units - self.reserved_base_units


@dataclass(frozen=True, slots=True)
class SponsoredExecutionPlan:
    plan_id: str
    provider_id: str
    transaction_sha256: str
    customer_id: str
    payment_asset_id: str
    sponsor_fee_base_units: int
    client_service_fee_base_units: int
    roles_validated: bool
    approved: bool
    blockers: tuple[str, ...]
    signing_allowed: bool = False
    submission_allowed: bool = False

    def __post_init__(self) -> None:
        require_id(self.plan_id, "plan_id")
        require_id(self.provider_id, "provider_id")
        require_sha256(self.transaction_sha256, "transaction_sha256")
        require_id(self.customer_id, "customer_id")
        require_id(self.payment_asset_id, "payment_asset_id")
        require_nonnegative(self.sponsor_fee_base_units, "sponsor_fee_base_units")
        require_nonnegative(
            self.client_service_fee_base_units, "client_service_fee_base_units"
        )
        if self.signing_allowed or self.submission_allowed:
            raise ValueError("AGG-14 sponsored plan cannot sign or submit")
        if self.approved and self.blockers:
            raise ValueError("approved sponsored plan cannot retain blockers")


def plan_sponsored_execution(
    *,
    plan_id: str,
    capability: PaymasterCapability,
    budget: SponsorBudget,
    transaction_sha256: str,
    customer_id: str,
    payment_asset_id: str,
    sponsor_fee_base_units: int,
    client_service_fee_base_units: int,
    roles_validated: bool,
) -> SponsoredExecutionPlan:
    blockers: list[str] = []
    if not capability.externally_verified:
        blockers.append("PAYMASTER_CAPABILITY_UNVERIFIED")
    if not capability.fee_payer_funded:
        blockers.append("PAYMASTER_FEE_PAYER_UNFUNDED")
    if payment_asset_id not in capability.accepted_payment_assets:
        blockers.append("PAYMASTER_PAYMENT_ASSET_UNSUPPORTED")
    if not roles_validated:
        blockers.append("PAYMASTER_TRANSACTION_ROLES_INVALID")
    if sponsor_fee_base_units > capability.max_sponsor_base_units:
        blockers.append("PAYMASTER_PROVIDER_CAP_EXCEEDED")
    if sponsor_fee_base_units > budget.per_request_cap_base_units:
        blockers.append("PAYMASTER_REQUEST_CAP_EXCEEDED")
    if sponsor_fee_base_units > budget.loss_cap_base_units:
        blockers.append("PAYMASTER_LOSS_CAP_EXCEEDED")
    if sponsor_fee_base_units > budget.free_base_units:
        blockers.append("PAYMASTER_SPONSOR_FUNDS_INSUFFICIENT")
    return SponsoredExecutionPlan(
        plan_id=plan_id,
        provider_id=capability.provider_id,
        transaction_sha256=transaction_sha256,
        customer_id=customer_id,
        payment_asset_id=payment_asset_id,
        sponsor_fee_base_units=sponsor_fee_base_units,
        client_service_fee_base_units=client_service_fee_base_units,
        roles_validated=roles_validated,
        approved=not blockers,
        blockers=tuple(blockers),
    )


@dataclass(frozen=True, slots=True)
class KeeperAuthorization:
    authorization_id: str
    customer_id: str
    account_id: str
    action_scope: tuple[str, ...]
    max_debit_base_units: int
    service_fee_base_units: int
    policy_sha256: str
    approved: bool

    def __post_init__(self) -> None:
        require_id(self.authorization_id, "authorization_id")
        require_id(self.customer_id, "customer_id")
        require_text(self.account_id, "account_id")
        unique_nonempty(self.action_scope, "action_scope")
        require_nonnegative(self.max_debit_base_units, "max_debit_base_units")
        require_nonnegative(self.service_fee_base_units, "service_fee_base_units")
        require_sha256(self.policy_sha256, "policy_sha256")


@dataclass(frozen=True, slots=True)
class KeeperOperation:
    operation_id: str
    authorization_id: str
    account_id: str
    action: str
    desired_state_sha256: str
    observed_state_sha256: str
    worst_debit_base_units: int
    service_fee_base_units: int
    permitted: bool
    blockers: tuple[str, ...]
    client_capital_is_trading_capital: bool = False
    signing_allowed: bool = False
    submission_allowed: bool = False

    def __post_init__(self) -> None:
        require_id(self.operation_id, "operation_id")
        require_id(self.authorization_id, "authorization_id")
        require_text(self.account_id, "account_id")
        require_id(self.action, "action")
        require_sha256(self.desired_state_sha256, "desired_state_sha256")
        require_sha256(self.observed_state_sha256, "observed_state_sha256")
        require_nonnegative(self.worst_debit_base_units, "worst_debit_base_units")
        require_nonnegative(self.service_fee_base_units, "service_fee_base_units")
        if self.client_capital_is_trading_capital:
            raise ValueError("client capital cannot become trading capital")
        if self.signing_allowed or self.submission_allowed:
            raise ValueError("AGG-14 keeper plan cannot sign or submit")
        if self.permitted and self.blockers:
            raise ValueError("permitted keeper operation cannot have blockers")


def plan_keeper_operation(
    *,
    operation_id: str,
    authorization: KeeperAuthorization,
    action: str,
    desired_state_sha256: str,
    observed_state_sha256: str,
    worst_debit_base_units: int,
) -> KeeperOperation:
    blockers: list[str] = []
    if not authorization.approved:
        blockers.append("KEEPER_AUTHORIZATION_NOT_APPROVED")
    if action not in authorization.action_scope:
        blockers.append("KEEPER_ACTION_OUT_OF_SCOPE")
    if worst_debit_base_units > authorization.max_debit_base_units:
        blockers.append("KEEPER_MAX_DEBIT_EXCEEDED")
    return KeeperOperation(
        operation_id=operation_id,
        authorization_id=authorization.authorization_id,
        account_id=authorization.account_id,
        action=action,
        desired_state_sha256=desired_state_sha256,
        observed_state_sha256=observed_state_sha256,
        worst_debit_base_units=worst_debit_base_units,
        service_fee_base_units=authorization.service_fee_base_units,
        permitted=not blockers,
        blockers=tuple(blockers),
    )


class DataEvidenceKind(StrEnum):
    OBSERVED = "observed"
    SIMULATED = "simulated"
    DEMO = "demo"


@dataclass(frozen=True, slots=True)
class DataEvidenceArtifact:
    artifact_id: str
    version: str
    artifact_sha256: str
    provenance_sha256: str
    evidence_kind: DataEvidenceKind
    distribution_allowed: bool
    access_scopes: tuple[str, ...]
    max_queries_per_lease: int
    stale: bool = False
    contains_secrets: bool = False

    def __post_init__(self) -> None:
        require_id(self.artifact_id, "artifact_id")
        require_text(self.version, "version")
        require_sha256(self.artifact_sha256, "artifact_sha256")
        require_sha256(self.provenance_sha256, "provenance_sha256")
        unique_nonempty(self.access_scopes, "access_scope")
        require_positive(self.max_queries_per_lease, "max_queries_per_lease")
        if self.contains_secrets:
            raise ValueError("data evidence API cannot register secret-bearing artifacts")


@dataclass(frozen=True, slots=True)
class DataEvidenceResponse:
    artifact_id: str
    version: str
    evidence_kind: DataEvidenceKind
    artifact_sha256: str
    provenance_sha256: str
    stale: bool
    remaining_queries: int
    actual_pnl_claimed: bool


class DataEvidenceApi:
    """Pure policy surface; transport/auth adapters remain outside AGG-14."""

    def __init__(self, artifacts: Iterable[DataEvidenceArtifact]) -> None:
        self._artifacts: dict[str, DataEvidenceArtifact] = {}
        self._usage: dict[tuple[str, str], int] = {}
        for artifact in artifacts:
            if artifact.artifact_id in self._artifacts:
                raise ValueError("duplicate data evidence artifact_id")
            self._artifacts[artifact.artifact_id] = artifact

    def read(
        self,
        *,
        artifact_id: str,
        lease_id: str,
        access_scope: str,
    ) -> DataEvidenceResponse:
        require_id(lease_id, "lease_id")
        artifact = self._artifacts.get(artifact_id)
        if artifact is None:
            raise ResearchFailure(
                "DATA_EVIDENCE_ARTIFACT_MISSING",
                stage="data-api",
                description="requested artifact is not registered",
            )
        if not artifact.distribution_allowed:
            raise ResearchFailure(
                "DATA_EVIDENCE_DISTRIBUTION_DENIED",
                stage="data-api",
                description="artifact licence/rights prohibit distribution",
            )
        if access_scope not in artifact.access_scopes:
            raise ResearchFailure(
                "DATA_EVIDENCE_SCOPE_DENIED",
                stage="data-api",
                description="lease scope does not grant this artifact",
            )
        key = (lease_id, artifact_id)
        used = self._usage.get(key, 0)
        if used >= artifact.max_queries_per_lease:
            raise ResearchFailure(
                "DATA_EVIDENCE_QUERY_BUDGET_EXHAUSTED",
                stage="data-api",
                description="lease query budget is exhausted",
            )
        self._usage[key] = used + 1
        return DataEvidenceResponse(
            artifact_id=artifact.artifact_id,
            version=artifact.version,
            evidence_kind=artifact.evidence_kind,
            artifact_sha256=artifact.artifact_sha256,
            provenance_sha256=artifact.provenance_sha256,
            stale=artifact.stale,
            remaining_queries=artifact.max_queries_per_lease - used - 1,
            actual_pnl_claimed=artifact.evidence_kind is DataEvidenceKind.OBSERVED,
        )


@dataclass(frozen=True, slots=True)
class ApplicationOrDisclosureReceipt:
    workflow_id: str
    program_id: str
    rules_sha256: str
    evidence_sha256: str
    identity_approved: bool
    security_scope_authorized: bool
    contains_private_details: bool
    private_details_approved: bool
    submitted: bool = False
    exploitation_performed: bool = False
    revenue_recognized: bool = False

    def __post_init__(self) -> None:
        require_id(self.workflow_id, "workflow_id")
        require_id(self.program_id, "program_id")
        require_sha256(self.rules_sha256, "rules_sha256")
        require_sha256(self.evidence_sha256, "evidence_sha256")
        if not self.identity_approved:
            raise ResearchFailure(
                "APPLICATION_IDENTITY_APPROVAL_MISSING",
                stage="grant-bounty",
                description="user identity approval is required",
            )
        if self.contains_private_details and not self.private_details_approved:
            raise ResearchFailure(
                "DISCLOSURE_PRIVATE_DETAILS_NOT_APPROVED",
                stage="grant-bounty",
                description="private disclosure details lack approval",
            )
        if self.exploitation_performed:
            raise ValueError("research workflow cannot perform unsolicited exploitation")
        if self.revenue_recognized:
            raise ValueError("application/disclosure is not recognized revenue")
        if self.submitted:
            raise ValueError("offline AGG-14 receipt cannot claim remote submission")


class RevenueCategory(StrEnum):
    ARBITRAGE_PNL = "arbitrage-pnl"
    SERVICE_FEE = "service-fee"
    REBATE = "rebate"
    GRANT = "grant"
    RENT_RECLAIM = "rent-reclaim"
    INVESTMENT = "investment"
    CLIENT_FUNDS = "client-funds"


class CashState(StrEnum):
    PENDING = "pending"
    SETTLED = "settled"


@dataclass(frozen=True, slots=True)
class RevenueCashflow:
    cashflow_id: str
    external_event_id: str
    category: RevenueCategory
    asset_id: str
    base_units: int
    counterparty: str
    state: CashState
    evidence_sha256: str

    def __post_init__(self) -> None:
        require_id(self.cashflow_id, "cashflow_id")
        require_id(self.external_event_id, "external_event_id")
        require_id(self.asset_id, "asset_id")
        if isinstance(self.base_units, bool) or not isinstance(self.base_units, int):
            raise ValueError("base_units must be a signed integer")
        require_text(self.counterparty, "counterparty")
        require_sha256(self.evidence_sha256, "evidence_sha256")


class RevenueAttributionLedger:
    """Separate product/research attribution; never a trading capital authority."""

    def __init__(self) -> None:
        self._by_id: dict[str, RevenueCashflow] = {}
        self._by_external_event: dict[str, str] = {}

    def record(self, cashflow: RevenueCashflow) -> None:
        existing = self._by_id.get(cashflow.cashflow_id)
        if existing is not None:
            if existing != cashflow:
                raise ResearchFailure(
                    "PRODUCT_CASHFLOW_ID_CONFLICT",
                    stage="product-accounting",
                    description="cashflow id reused with different attribution",
                )
            return
        prior_category = self._by_external_event.get(cashflow.external_event_id)
        if prior_category is not None:
            raise ResearchFailure(
                "PRODUCT_EXTERNAL_EVENT_DOUBLE_ATTRIBUTION",
                stage="product-accounting",
                description="one external event cannot be both trading and product revenue",
            )
        self._by_id[cashflow.cashflow_id] = cashflow
        self._by_external_event[cashflow.external_event_id] = cashflow.category.value

    def settled_total(self, *, category: RevenueCategory, asset_id: str) -> int:
        return sum(
            row.base_units
            for row in self._by_id.values()
            if row.category is category
            and row.asset_id == asset_id
            and row.state is CashState.SETTLED
        )

    def trading_pnl(self, asset_id: str) -> int:
        return self.settled_total(category=RevenueCategory.ARBITRAGE_PNL, asset_id=asset_id)

    def product_revenue(self, asset_id: str) -> int:
        included = {
            RevenueCategory.SERVICE_FEE,
            RevenueCategory.REBATE,
            RevenueCategory.GRANT,
        }
        return sum(
            row.base_units
            for row in self._by_id.values()
            if row.category in included
            and row.asset_id == asset_id
            and row.state is CashState.SETTLED
        )

    def non_alpha_recovery(self, asset_id: str) -> int:
        return self.settled_total(category=RevenueCategory.RENT_RECLAIM, asset_id=asset_id)

    def client_funds(self, asset_id: str) -> int:
        return self.settled_total(category=RevenueCategory.CLIENT_FUNDS, asset_id=asset_id)

    def export(self) -> dict[str, object]:
        rows = [asdict(value) for _, value in sorted(self._by_id.items())]
        return {
            "schema": "agg14.revenue-attribution-ledger.v1",
            "rows": rows,
            "sha256": hash_json("agg14/revenue-ledger/v1", rows),
            "trading_capital_authority": False,
        }


__all__ = [
    "ApplicationOrDisclosureReceipt",
    "CashState",
    "DataEvidenceApi",
    "DataEvidenceArtifact",
    "DataEvidenceKind",
    "DataEvidenceResponse",
    "KeeperAuthorization",
    "KeeperOperation",
    "PaymasterCapability",
    "RevenueAttributionLedger",
    "RevenueCashflow",
    "RevenueCategory",
    "SponsorBudget",
    "SponsoredExecutionPlan",
    "plan_keeper_operation",
    "plan_sponsored_execution",
]
