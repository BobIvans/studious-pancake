"""MPR-CLOSE-26 economic truth and settlement lineage gate.

Offline, sender-free acceptance contract that keeps quoted, simulated,
paper-estimated and finalized-on-chain economics separate.  It never performs
network I/O, imports senders, signs, submits or promotes live trading.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

MPR_CLOSE_26_SCHEMA = "mpr-close-26.economic-truth.v1"
MPR_CLOSE_26_READY = "mpr_close_26_economic_truth_ready"
MPR_CLOSE_26_BLOCKED = "blocked_mpr_close_26_economic_truth"
_MIN_DIGEST_LENGTH = 32
_PLACEHOLDER_DIGESTS = frozenset({"", "0", "0x0", "todo", "fake", "placeholder"})


class EconomicLineage(StrEnum):
    QUOTED = "quoted"
    SIMULATED = "simulated"
    PAPER_ESTIMATED = "paper_estimated"
    FINALIZED_ON_CHAIN = "finalized_on_chain"
    SYNTHETIC = "synthetic"
    RECORDED = "recorded"


class SettlementState(StrEnum):
    ACKNOWLEDGED = "acknowledged"
    SUBMITTED = "submitted"
    LANDED = "landed"
    SIMULATED = "simulated"
    PAPER_ESTIMATED = "paper_estimated"
    FINALIZED = "finalized"
    FAILED = "failed"
    UNCLED = "uncled"
    REBROADCAST = "rebroadcast"


class JitoEvidenceKind(StrEnum):
    NONE = "none"
    BUNDLE_ACK = "bundle_ack"
    BUNDLE_LANDED = "bundle_landed"
    FINALIZED_TRANSACTION = "finalized_transaction"
    UNCLE_REBROADCAST = "uncle_rebroadcast"


class EconomicGateState(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class ReportMetricName(StrEnum):
    PAPER_PNL_ESTIMATED = "paper_pnl_estimated"
    SHADOW_DETECTED_EDGE = "shadow_detected_edge"
    SIMULATED_NET_EDGE = "simulated_net_edge"
    FINALIZED_REALIZED_PNL = "finalized_realized_pnl"


@dataclass(frozen=True, slots=True)
class LifecycleCostBreakdown:
    network_fee_lamports: int = 0
    priority_fee_lamports: int = 0
    rent_lamports: int = 0
    ata_creation_lamports: int = 0
    ata_closure_refund_lamports: int = 0
    wsol_wrap_lamports: int = 0
    wsol_unwrap_refund_lamports: int = 0
    flashloan_repayment_lamports: int = 0
    failed_attempt_lamports: int = 0
    retry_lamports: int = 0

    def __post_init__(self) -> None:
        for name, value in self.to_dict().items():
            _require_non_negative(name, value)

    @property
    def gross_debit_lamports(self) -> int:
        return (
            self.network_fee_lamports
            + self.priority_fee_lamports
            + self.rent_lamports
            + self.ata_creation_lamports
            + self.wsol_wrap_lamports
            + self.flashloan_repayment_lamports
            + self.failed_attempt_lamports
            + self.retry_lamports
        )

    @property
    def net_debit_lamports(self) -> int:
        return (
            self.gross_debit_lamports
            - self.ata_closure_refund_lamports
            - self.wsol_unwrap_refund_lamports
        )

    def to_dict(self) -> dict[str, int]:
        return {
            name: getattr(self, name)
            for name in (
                "network_fee_lamports",
                "priority_fee_lamports",
                "rent_lamports",
                "ata_creation_lamports",
                "ata_closure_refund_lamports",
                "wsol_wrap_lamports",
                "wsol_unwrap_refund_lamports",
                "flashloan_repayment_lamports",
                "failed_attempt_lamports",
                "retry_lamports",
            )
        }


@dataclass(frozen=True, slots=True)
class QuoteEconomics:
    quote_id: str
    route_digest: str
    input_mint: str
    output_mint: str
    input_amount_lamports: int
    expected_output_lamports: int
    quoted_profit_lamports: int
    context_slot: int
    expiry_slot: int
    cost_budget: LifecycleCostBreakdown = field(default_factory=LifecycleCostBreakdown)
    lineage: EconomicLineage = EconomicLineage.QUOTED

    def __post_init__(self) -> None:
        _require_text(self.quote_id, "quote_id")
        _require_digest(self.route_digest, "route_digest")
        _require_text(self.input_mint, "input_mint")
        _require_text(self.output_mint, "output_mint")
        _require_non_negative("input_amount_lamports", self.input_amount_lamports)
        _require_non_negative("expected_output_lamports", self.expected_output_lamports)
        _require_slot_order(self.context_slot, self.expiry_slot)
        object.__setattr__(self, "lineage", EconomicLineage.QUOTED)

    def to_dict(self) -> dict[str, Any]:
        return _economics_dict(
            self,
            "quote_economics.v1",
            quoted_profit_lamports=self.quoted_profit_lamports,
            realized=False,
        )


@dataclass(frozen=True, slots=True)
class SimulationEconomics:
    simulation_id: str
    quote_id: str
    route_digest: str
    message_digest: str
    final_simulation_digest: str
    blockhash: str
    context_slot: int
    simulated_profit_lamports: int
    cost_budget: LifecycleCostBreakdown = field(default_factory=LifecycleCostBreakdown)
    ok: bool = True
    lineage: EconomicLineage = EconomicLineage.SIMULATED

    def __post_init__(self) -> None:
        _require_text(self.simulation_id, "simulation_id")
        _require_text(self.quote_id, "quote_id")
        _require_digest(self.route_digest, "route_digest")
        _require_digest(self.message_digest, "message_digest")
        _require_digest(self.final_simulation_digest, "final_simulation_digest")
        _require_text(self.blockhash, "blockhash")
        _require_non_negative("context_slot", self.context_slot)
        object.__setattr__(self, "lineage", EconomicLineage.SIMULATED)

    def to_dict(self) -> dict[str, Any]:
        return _economics_dict(
            self,
            "simulation_economics.v1",
            simulated_profit_lamports=self.simulated_profit_lamports,
            realized=False,
        )


@dataclass(frozen=True, slots=True)
class PaperEconomics:
    paper_outcome_id: str
    quote_id: str
    simulation_id: str
    message_digest: str
    paper_estimated_net_lamports: int
    lifecycle_costs: LifecycleCostBreakdown = field(
        default_factory=LifecycleCostBreakdown
    )
    terminal_state: SettlementState = SettlementState.PAPER_ESTIMATED
    lineage: EconomicLineage = EconomicLineage.PAPER_ESTIMATED

    def __post_init__(self) -> None:
        _require_text(self.paper_outcome_id, "paper_outcome_id")
        _require_text(self.quote_id, "quote_id")
        _require_text(self.simulation_id, "simulation_id")
        _require_digest(self.message_digest, "message_digest")
        if self.terminal_state is not SettlementState.PAPER_ESTIMATED:
            raise ValueError("paper economics must remain paper_estimated")
        object.__setattr__(self, "lineage", EconomicLineage.PAPER_ESTIMATED)

    def to_dict(self) -> dict[str, Any]:
        return _economics_dict(
            self,
            "paper_economics.v1",
            paper_estimated_net_lamports=self.paper_estimated_net_lamports,
            realized=False,
        )


@dataclass(frozen=True, slots=True)
class TokenAccountDelta:
    mint: str
    owner: str
    pre_amount_base_units: int
    post_amount_base_units: int

    def __post_init__(self) -> None:
        _require_text(self.mint, "mint")
        _require_text(self.owner, "owner")
        _require_non_negative("pre_amount_base_units", self.pre_amount_base_units)
        _require_non_negative("post_amount_base_units", self.post_amount_base_units)

    @property
    def delta_base_units(self) -> int:
        return self.post_amount_base_units - self.pre_amount_base_units

    def to_dict(self) -> dict[str, Any]:
        return {
            "mint": self.mint,
            "owner": self.owner,
            "pre_amount_base_units": self.pre_amount_base_units,
            "post_amount_base_units": self.post_amount_base_units,
            "delta_base_units": self.delta_base_units,
        }


@dataclass(frozen=True, slots=True)
class FinalizedChainEconomics:
    signature: str
    message_digest: str
    finalized_slot: int
    payer_pre_lamports: int
    payer_post_lamports: int
    token_deltas: tuple[TokenAccountDelta, ...] = ()
    network_fee_lamports: int = 0
    priority_fee_lamports: int = 0
    state: SettlementState = SettlementState.FINALIZED
    lineage: EconomicLineage = EconomicLineage.FINALIZED_ON_CHAIN

    def __post_init__(self) -> None:
        _require_text(self.signature, "signature")
        _require_digest(self.message_digest, "message_digest")
        _require_non_negative("finalized_slot", self.finalized_slot)
        _require_non_negative("payer_pre_lamports", self.payer_pre_lamports)
        _require_non_negative("payer_post_lamports", self.payer_post_lamports)
        _require_non_negative("network_fee_lamports", self.network_fee_lamports)
        _require_non_negative("priority_fee_lamports", self.priority_fee_lamports)
        if self.state is not SettlementState.FINALIZED:
            raise ValueError("finalized economics require finalized state")
        object.__setattr__(self, "token_deltas", tuple(self.token_deltas))
        object.__setattr__(self, "lineage", EconomicLineage.FINALIZED_ON_CHAIN)

    @property
    def payer_delta_lamports(self) -> int:
        return self.payer_post_lamports - self.payer_pre_lamports

    @property
    def realized_payer_pnl_lamports(self) -> int:
        return (
            self.payer_delta_lamports
            - self.network_fee_lamports
            - self.priority_fee_lamports
        )

    def token_delta_by_mint(self) -> dict[str, int]:
        totals: defaultdict[str, int] = defaultdict(int)
        for delta in self.token_deltas:
            totals[delta.mint] += delta.delta_base_units
        return dict(totals)

    def to_dict(self) -> dict[str, Any]:
        return _economics_dict(
            self,
            "finalized_chain_economics.v1",
            payer_delta_lamports=self.payer_delta_lamports,
            realized_payer_pnl_lamports=self.realized_payer_pnl_lamports,
            token_deltas=[delta.to_dict() for delta in self.token_deltas],
            token_delta_by_mint=self.token_delta_by_mint(),
            realized=True,
        )


@dataclass(frozen=True, slots=True)
class ReportMetric:
    name: ReportMetricName
    value_lamports: int
    lineage: EconomicLineage
    source_id: str
    bucket: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.source_id, "source_id")
        required = {
            ReportMetricName.PAPER_PNL_ESTIMATED: EconomicLineage.PAPER_ESTIMATED,
            ReportMetricName.SIMULATED_NET_EDGE: EconomicLineage.SIMULATED,
            ReportMetricName.FINALIZED_REALIZED_PNL: EconomicLineage.FINALIZED_ON_CHAIN,
        }.get(self.name)
        if required is not None and self.lineage is not required:
            raise ValueError(f"{self.name.value} requires {required.value} lineage")

    @property
    def report_key(self) -> str:
        return self.bucket or self.name.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name.value,
            "value_lamports": self.value_lamports,
            "lineage": self.lineage.value,
            "source_id": self.source_id,
            "bucket": self.bucket,
        }


@dataclass(frozen=True, slots=True)
class InstructionAccount:
    address: str
    is_writable: bool = False
    is_signer: bool = False

    def __post_init__(self) -> None:
        _require_text(self.address, "address")


@dataclass(frozen=True, slots=True)
class InstructionFirewallPolicy:
    expected_message_digest: str
    final_simulation_message_digest: str
    allowed_writable_accounts: frozenset[str]
    allowed_signer_accounts: frozenset[str]
    same_message_tip_accounts: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _require_digest(self.expected_message_digest, "expected_message_digest")
        _require_digest(
            self.final_simulation_message_digest,
            "final_simulation_message_digest",
        )
        object.__setattr__(
            self,
            "allowed_writable_accounts",
            frozenset(self.allowed_writable_accounts),
        )
        object.__setattr__(
            self,
            "allowed_signer_accounts",
            frozenset(self.allowed_signer_accounts),
        )
        object.__setattr__(
            self,
            "same_message_tip_accounts",
            frozenset(self.same_message_tip_accounts),
        )


@dataclass(frozen=True, slots=True)
class InstructionFirewallResult:
    allowed: bool
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "blockers", _string_tuple(self.blockers))

    def to_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "blockers": list(self.blockers)}


@dataclass(frozen=True, slots=True)
class JitoSettlementEvidence:
    kind: JitoEvidenceKind = JitoEvidenceKind.NONE
    message_digest: str | None = None
    bundle_id: str | None = None
    finalized_signature: str | None = None
    claims_settlement: bool = False

    def __post_init__(self) -> None:
        if self.message_digest is not None:
            _require_digest(self.message_digest, "message_digest")
        if self.finalized_signature is not None:
            _require_text(self.finalized_signature, "finalized_signature")

    @property
    def transport_only(self) -> bool:
        return self.kind in {
            JitoEvidenceKind.BUNDLE_ACK,
            JitoEvidenceKind.BUNDLE_LANDED,
            JitoEvidenceKind.UNCLE_REBROADCAST,
        }

    @property
    def finality_capable(self) -> bool:
        return self.kind is JitoEvidenceKind.FINALIZED_TRANSACTION

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.transport_only and self.claims_settlement:
            blockers.append("jito_transport_evidence_claims_settlement")
        if self.kind is JitoEvidenceKind.FINALIZED_TRANSACTION:
            if not self.finalized_signature:
                blockers.append("jito_finalized_evidence_missing_signature")
            if not self.message_digest:
                blockers.append("jito_finalized_evidence_missing_message_digest")
        if self.kind is JitoEvidenceKind.UNCLE_REBROADCAST:
            blockers.append(
                "jito_uncle_rebroadcast_requires_fail_closed_classification"
            )
        return tuple(blockers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "message_digest": self.message_digest,
            "bundle_id": self.bundle_id,
            "finalized_signature": self.finalized_signature,
            "claims_settlement": self.claims_settlement,
            "transport_only": self.transport_only,
            "finality_capable": self.finality_capable,
            "blockers": list(self.blockers()),
        }


@dataclass(frozen=True, slots=True)
class EconomicTruthBundle:
    quote: QuoteEconomics
    simulation: SimulationEconomics
    paper: PaperEconomics | None = None
    finalized: FinalizedChainEconomics | None = None
    jito: JitoSettlementEvidence = field(default_factory=JitoSettlementEvidence)
    firewall: InstructionFirewallResult = field(
        default_factory=lambda: InstructionFirewallResult(True)
    )
    report_metrics: tuple[ReportMetric, ...] = ()
    schema_version: str = MPR_CLOSE_26_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "report_metrics", tuple(self.report_metrics))


@dataclass(frozen=True, slots=True)
class EconomicTruthAssessment:
    state: EconomicGateState
    reason_code: str
    blockers: tuple[str, ...]
    reports: Mapping[str, list[dict[str, Any]]]
    schema_version: str = MPR_CLOSE_26_SCHEMA
    live_enabled: bool = False
    signer_reachable: bool = False
    sender_reachable: bool = False
    finalized_realized_pnl_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "blockers", _string_tuple(self.blockers))
        object.__setattr__(
            self,
            "reports",
            MappingProxyType({key: list(value) for key, value in self.reports.items()}),
        )
        object.__setattr__(self, "live_enabled", False)
        object.__setattr__(self, "signer_reachable", False)
        object.__setattr__(self, "sender_reachable", False)
        object.__setattr__(
            self,
            "finalized_realized_pnl_allowed",
            self.finalized_realized_pnl_allowed and not self.blockers,
        )

    @property
    def ready(self) -> bool:
        return self.state is EconomicGateState.READY

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "ready": self.ready,
            "reason_code": self.reason_code,
            "blockers": list(self.blockers),
            "reports": dict(self.reports),
            "safety": {
                "live_enabled": self.live_enabled,
                "signer_reachable": self.signer_reachable,
                "sender_reachable": self.sender_reachable,
                "finalized_realized_pnl_allowed": self.finalized_realized_pnl_allowed,
            },
        }


def evaluate_instruction_firewall(
    accounts: Iterable[InstructionAccount],
    policy: InstructionFirewallPolicy,
    *,
    message_digest: str,
    compute_budget_mutated_after_final_simulation: bool = False,
    hidden_tip_transfer_account: str | None = None,
) -> InstructionFirewallResult:
    _require_digest(message_digest, "message_digest")
    blockers: list[str] = []
    if message_digest != policy.expected_message_digest:
        blockers.append("firewall_message_digest_mismatch")
    if policy.expected_message_digest != policy.final_simulation_message_digest:
        blockers.append("firewall_final_simulation_digest_mismatch")
    if compute_budget_mutated_after_final_simulation:
        blockers.append("firewall_compute_budget_mutated_after_final_simulation")
    if hidden_tip_transfer_account not in (None, *policy.same_message_tip_accounts):
        blockers.append("firewall_hidden_tip_transfer_outside_same_message_policy")
    for account in accounts:
        if (
            account.is_writable
            and account.address not in policy.allowed_writable_accounts
        ):
            blockers.append(f"firewall_unknown_writable_account:{account.address}")
        if account.is_signer and account.address not in policy.allowed_signer_accounts:
            blockers.append(f"firewall_unknown_signer_account:{account.address}")
    unique = tuple(dict.fromkeys(blockers))
    return InstructionFirewallResult(allowed=not unique, blockers=unique)


def evaluate_economic_truth_bundle(
    bundle: EconomicTruthBundle,
) -> EconomicTruthAssessment:
    blockers: list[str] = []
    if bundle.quote.quote_id != bundle.simulation.quote_id:
        blockers.append("simulation_quote_id_mismatch")
    if bundle.quote.route_digest != bundle.simulation.route_digest:
        blockers.append("simulation_route_digest_mismatch")
    if bundle.paper is not None:
        if bundle.paper.quote_id != bundle.quote.quote_id:
            blockers.append("paper_quote_id_mismatch")
        if bundle.paper.simulation_id != bundle.simulation.simulation_id:
            blockers.append("paper_simulation_id_mismatch")
        if bundle.paper.message_digest != bundle.simulation.message_digest:
            blockers.append("paper_message_digest_mismatch")
    if bundle.finalized is None:
        if _has_metric(bundle.report_metrics, ReportMetricName.FINALIZED_REALIZED_PNL):
            blockers.append("finalized_realized_pnl_without_finalized_settlement")
    else:
        if bundle.finalized.message_digest != bundle.simulation.message_digest:
            blockers.append("finalized_message_digest_mismatch")
    if not bundle.simulation.ok:
        blockers.append("simulation_not_ok")
    if bundle.simulation.message_digest != bundle.simulation.final_simulation_digest:
        blockers.append("simulation_message_mutated_after_final_simulation")
    blockers.extend(bundle.jito.blockers())
    if bundle.jito.finality_capable and bundle.finalized is not None:
        if bundle.jito.message_digest != bundle.finalized.message_digest:
            blockers.append("jito_finalized_message_digest_mismatch")
        if bundle.jito.finalized_signature != bundle.finalized.signature:
            blockers.append("jito_finalized_signature_mismatch")
    if not bundle.firewall.allowed:
        blockers.extend(bundle.firewall.blockers)
    blockers.extend(_mixed_lineage_blockers(bundle.report_metrics))
    unique = tuple(dict.fromkeys(blockers))
    state = EconomicGateState.BLOCKED if unique else EconomicGateState.READY
    return EconomicTruthAssessment(
        state=state,
        reason_code=MPR_CLOSE_26_BLOCKED if unique else MPR_CLOSE_26_READY,
        blockers=unique,
        reports=build_lineage_reports(bundle.report_metrics),
        finalized_realized_pnl_allowed=bundle.finalized is not None,
    )


def build_lineage_reports(
    metrics: Sequence[ReportMetric],
) -> dict[str, list[dict[str, Any]]]:
    reports: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for metric in metrics:
        reports[metric.name.value].append(metric.to_dict())
    return dict(reports)


def _mixed_lineage_blockers(metrics: Sequence[ReportMetric]) -> tuple[str, ...]:
    lineages_by_bucket: defaultdict[str, set[EconomicLineage]] = defaultdict(set)
    for metric in metrics:
        lineages_by_bucket[metric.report_key].add(metric.lineage)
    return tuple(
        f"lineage_quarantine_mixed_report_bucket:{bucket}"
        for bucket, lineages in sorted(lineages_by_bucket.items())
        if len(lineages) > 1
    )


def _has_metric(metrics: Sequence[ReportMetric], name: ReportMetricName) -> bool:
    return any(metric.name is name for metric in metrics)


def _economics_dict(instance: object, schema: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"schema": schema}
    for name in getattr(instance, "__dataclass_fields__", {}):
        value = getattr(instance, name)
        if isinstance(value, StrEnum):
            payload[name] = value.value
        elif isinstance(value, LifecycleCostBreakdown):
            payload[name] = value.to_dict()
        elif isinstance(value, tuple):
            payload[name] = [
                item.to_dict() if hasattr(item, "to_dict") else item for item in value
            ]
        else:
            payload[name] = value
    payload.update(extra)
    return payload


def _require_digest(value: str, name: str) -> None:
    _require_text(value, name)
    normalized = value.strip().lower()
    if normalized in _PLACEHOLDER_DIGESTS or len(normalized) < _MIN_DIGEST_LENGTH:
        raise ValueError(f"{name} must be a non-placeholder digest")


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_non_negative(name: str, value: int) -> None:
    if not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _require_slot_order(context_slot: int, expiry_slot: int) -> None:
    _require_non_negative("context_slot", context_slot)
    _require_non_negative("expiry_slot", expiry_slot)
    if expiry_slot <= context_slot:
        raise ValueError("expiry_slot must be greater than context_slot")


def _string_tuple(values: object) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        return (values,)
    if not isinstance(values, Iterable):
        return (str(values),)
    return tuple(str(value) for value in values)


__all__ = [
    "EconomicGateState",
    "EconomicLineage",
    "EconomicTruthAssessment",
    "EconomicTruthBundle",
    "FinalizedChainEconomics",
    "InstructionAccount",
    "InstructionFirewallPolicy",
    "InstructionFirewallResult",
    "JitoEvidenceKind",
    "JitoSettlementEvidence",
    "LifecycleCostBreakdown",
    "MPR_CLOSE_26_BLOCKED",
    "MPR_CLOSE_26_READY",
    "MPR_CLOSE_26_SCHEMA",
    "PaperEconomics",
    "QuoteEconomics",
    "ReportMetric",
    "ReportMetricName",
    "SettlementState",
    "SimulationEconomics",
    "TokenAccountDelta",
    "build_lineage_reports",
    "evaluate_economic_truth_bundle",
    "evaluate_instruction_firewall",
]
