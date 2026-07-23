"""MPR-26 finalized economic truth and lineage quarantine.

This module is intentionally offline and side-effect-free. It does not sign,
submit, poll RPC/Jito, mutate runtime state, or enable live trading. It defines
a canonical evidence contract that keeps quoted, simulated, paper-estimated, and
finalized-realized economics separated, then fails closed when a report attempts
to promote non-finalized evidence into realized PnL or mix lineage domains.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any

SCHEMA_VERSION = "mpr26.finalized-economic-truth.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MPR26State(str, Enum):
    READY_FOR_FOUNDATION = "ready_for_mpr26_foundation"
    BLOCKED = "blocked"


class EconomicLayer(str, Enum):
    QUOTED = "quoted"
    SIMULATED = "simulated"
    PAPER_ESTIMATED = "paper_estimated"
    FINALIZED_REALIZED = "finalized_realized"


class Lineage(str, Enum):
    SYNTHETIC_FIXTURE = "synthetic_fixture"
    RECORDED_PROVIDER_FIXTURE = "recorded_provider_fixture"
    CREDENTIALED_PROVIDER_SNAPSHOT = "credentialed_provider_snapshot"
    FINALIZED_ONCHAIN_EVIDENCE = "finalized_onchain_evidence"


class SettlementStatus(str, Enum):
    NONE = "none"
    TRANSPORT_ACK = "transport_ack"
    SUBMITTED = "submitted"
    LANDED = "landed"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"


@dataclass(frozen=True)
class EconomicAmount:
    lamports: int
    asset_id: str

    def __post_init__(self) -> None:
        _strict_int(self.lamports, "lamports")
        if self.lamports < 0:
            raise ValueError("MPR26_NEGATIVE_AMOUNT")
        _text(self.asset_id, "asset_id")


@dataclass(frozen=True)
class CostBreakdown:
    network_fee: EconomicAmount
    priority_fee: EconomicAmount
    rent: EconomicAmount
    ata_create_close: EconomicAmount
    wsol_wrap_unwrap: EconomicAmount
    flashloan_repayment: EconomicAmount
    failed_attempt_budget: EconomicAmount
    retry_budget: EconomicAmount

    @property
    def total_lamports(self) -> int:
        values = (
            self.network_fee,
            self.priority_fee,
            self.rent,
            self.ata_create_close,
            self.wsol_wrap_unwrap,
            self.flashloan_repayment,
            self.failed_attempt_budget,
            self.retry_budget,
        )
        asset_ids = {item.asset_id for item in values}
        if len(asset_ids) != 1:
            raise ValueError("MPR26_COST_ASSET_MISMATCH")
        return sum(item.lamports for item in values)


@dataclass(frozen=True)
class EconomicObservation:
    layer: EconomicLayer
    lineage: Lineage
    gross_edge: EconomicAmount
    costs: CostBreakdown
    net_edge: EconomicAmount
    message_hash: str
    source_digest: str
    realized_claimed: bool = False

    def __post_init__(self) -> None:
        _sha(self.message_hash, "message_hash")
        _sha(self.source_digest, "source_digest")
        if self.gross_edge.asset_id != self.net_edge.asset_id:
            raise ValueError("MPR26_EDGE_ASSET_MISMATCH")
        if self.costs.network_fee.asset_id != self.gross_edge.asset_id:
            raise ValueError("MPR26_COST_EDGE_ASSET_MISMATCH")
        expected = max(0, self.gross_edge.lamports - self.costs.total_lamports)
        if self.net_edge.lamports != expected:
            raise ValueError("MPR26_NET_EDGE_MISMATCH")
        if self.layer is not EconomicLayer.FINALIZED_REALIZED:
            if self.realized_claimed:
                raise ValueError("MPR26_NON_FINALIZED_REALIZED_CLAIM")
        elif self.lineage is not Lineage.FINALIZED_ONCHAIN_EVIDENCE:
            raise ValueError("MPR26_FINALIZED_REQUIRES_ONCHAIN_LINEAGE")


@dataclass(frozen=True)
class FinalizedSettlementProof:
    settlement_status: SettlementStatus
    finalized_transaction_hash: str | None
    exact_message_hash: str
    payer_delta_hash: str | None
    token_delta_hash: str | None
    finality_slot: int | None
    ack_or_bundle_id_used_as_success: bool = False
    landed_used_as_success: bool = False

    def __post_init__(self) -> None:
        _sha(self.exact_message_hash, "exact_message_hash")
        _optional_sha(self.finalized_transaction_hash, "finalized_transaction_hash")
        _optional_sha(self.payer_delta_hash, "payer_delta_hash")
        _optional_sha(self.token_delta_hash, "token_delta_hash")
        if self.finality_slot is not None:
            _strict_int(self.finality_slot, "finality_slot")
            if self.finality_slot < 0:
                raise ValueError("MPR26_NEGATIVE_FINALITY_SLOT")


@dataclass(frozen=True)
class InstructionFirewallProof:
    no_unknown_writable_accounts: bool
    no_unknown_signer_accounts: bool
    no_hidden_tip_transfer: bool
    no_compute_budget_mutation_after_simulation: bool
    same_message_tip_policy: bool
    firewall_digest: str

    def __post_init__(self) -> None:
        _sha(self.firewall_digest, "firewall_digest")


@dataclass(frozen=True)
class JitoSettlementSemantics:
    bundle_ack_transport_only: bool
    bundle_landed_not_final_economics: bool
    uncle_rebroadcast_classified: bool
    tip_transaction_local_when_required: bool
    finalized_reconciliation_required: bool
    jito_contract_digest: str

    def __post_init__(self) -> None:
        _sha(self.jito_contract_digest, "jito_contract_digest")


@dataclass(frozen=True)
class LineageQuarantinePolicy:
    metrics_lineage_label_required: bool
    paper_and_realized_pnl_separated: bool
    synthetic_not_promotable: bool
    recorded_fixture_not_promotable: bool
    no_cross_lineage_aggregation_without_label: bool
    policy_digest: str

    def __post_init__(self) -> None:
        _sha(self.policy_digest, "policy_digest")


@dataclass(frozen=True)
class MPR26Evidence:
    observations: tuple[EconomicObservation, ...]
    settlement: FinalizedSettlementProof
    firewall: InstructionFirewallProof
    jito: JitoSettlementSemantics
    lineage_policy: LineageQuarantinePolicy
    unrestricted_live_available: bool = False


@dataclass(frozen=True)
class MPR26Blocker:
    code: str
    message: str


@dataclass(frozen=True)
class MPR26Report:
    schema_version: str
    state: MPR26State
    blockers: tuple[MPR26Blocker, ...]
    evidence_hash: str
    layers_present: tuple[str, ...]
    realized_pnl_allowed: bool
    paper_pnl_estimated_only: bool
    live_execution_allowed: bool


def evaluate_mpr26_evidence(evidence: MPR26Evidence) -> MPR26Report:
    """Evaluate the fail-closed MPR-26 evidence contract."""
    blockers: list[MPR26Blocker] = []
    _validate_layers(evidence.observations, blockers)
    _validate_settlement(evidence, blockers)
    _validate_firewall(evidence.firewall, blockers)
    _validate_jito(evidence.jito, blockers)
    _validate_lineage_policy(evidence.lineage_policy, blockers)
    if evidence.unrestricted_live_available:
        _add(
            blockers,
            "MPR26_UNRESTRICTED_LIVE_FORBIDDEN",
            "MPR-26 must not enable unrestricted live",
        )
    unique = tuple(_dedupe(blockers))
    layers = tuple(sorted({item.layer.value for item in evidence.observations}))
    return MPR26Report(
        schema_version=SCHEMA_VERSION,
        state=MPR26State.BLOCKED if unique else MPR26State.READY_FOR_FOUNDATION,
        blockers=unique,
        evidence_hash=_hash_dataclass(evidence),
        layers_present=layers,
        realized_pnl_allowed=False,
        paper_pnl_estimated_only=True,
        live_execution_allowed=False,
    )


def sample_ready_evidence() -> MPR26Evidence:
    asset = "SOL"
    digest_a = "a" * 64
    digest_b = "b" * 64
    digest_c = "c" * 64
    digest_d = "d" * 64
    costs = CostBreakdown(
        network_fee=EconomicAmount(5_000, asset),
        priority_fee=EconomicAmount(2_000, asset),
        rent=EconomicAmount(10_000, asset),
        ata_create_close=EconomicAmount(3_000, asset),
        wsol_wrap_unwrap=EconomicAmount(1_000, asset),
        flashloan_repayment=EconomicAmount(20_000, asset),
        failed_attempt_budget=EconomicAmount(4_000, asset),
        retry_budget=EconomicAmount(2_000, asset),
    )
    observations = (
        EconomicObservation(
            layer=EconomicLayer.QUOTED,
            lineage=Lineage.CREDENTIALED_PROVIDER_SNAPSHOT,
            gross_edge=EconomicAmount(100_000, asset),
            costs=costs,
            net_edge=EconomicAmount(53_000, asset),
            message_hash=digest_a,
            source_digest=digest_b,
        ),
        EconomicObservation(
            layer=EconomicLayer.SIMULATED,
            lineage=Lineage.CREDENTIALED_PROVIDER_SNAPSHOT,
            gross_edge=EconomicAmount(90_000, asset),
            costs=costs,
            net_edge=EconomicAmount(43_000, asset),
            message_hash=digest_a,
            source_digest=digest_c,
        ),
        EconomicObservation(
            layer=EconomicLayer.PAPER_ESTIMATED,
            lineage=Lineage.CREDENTIALED_PROVIDER_SNAPSHOT,
            gross_edge=EconomicAmount(80_000, asset),
            costs=costs,
            net_edge=EconomicAmount(33_000, asset),
            message_hash=digest_a,
            source_digest=digest_d,
        ),
        EconomicObservation(
            layer=EconomicLayer.FINALIZED_REALIZED,
            lineage=Lineage.FINALIZED_ONCHAIN_EVIDENCE,
            gross_edge=EconomicAmount(70_000, asset),
            costs=costs,
            net_edge=EconomicAmount(23_000, asset),
            message_hash=digest_a,
            source_digest=digest_a,
            realized_claimed=True,
        ),
    )
    return MPR26Evidence(
        observations=observations,
        settlement=FinalizedSettlementProof(
            settlement_status=SettlementStatus.FINALIZED,
            finalized_transaction_hash=digest_b,
            exact_message_hash=digest_a,
            payer_delta_hash=digest_c,
            token_delta_hash=digest_d,
            finality_slot=123,
        ),
        firewall=InstructionFirewallProof(
            no_unknown_writable_accounts=True,
            no_unknown_signer_accounts=True,
            no_hidden_tip_transfer=True,
            no_compute_budget_mutation_after_simulation=True,
            same_message_tip_policy=True,
            firewall_digest=digest_b,
        ),
        jito=JitoSettlementSemantics(
            bundle_ack_transport_only=True,
            bundle_landed_not_final_economics=True,
            uncle_rebroadcast_classified=True,
            tip_transaction_local_when_required=True,
            finalized_reconciliation_required=True,
            jito_contract_digest=digest_c,
        ),
        lineage_policy=LineageQuarantinePolicy(
            metrics_lineage_label_required=True,
            paper_and_realized_pnl_separated=True,
            synthetic_not_promotable=True,
            recorded_fixture_not_promotable=True,
            no_cross_lineage_aggregation_without_label=True,
            policy_digest=digest_d,
        ),
    )


def _validate_layers(
    observations: Sequence[EconomicObservation], blockers: list[MPR26Blocker]
) -> None:
    required = {layer for layer in EconomicLayer}
    present = {observation.layer for observation in observations}
    missing = sorted(layer.value for layer in required - present)
    if missing:
        _add(
            blockers,
            "MPR26_ECONOMIC_LAYERS_MISSING",
            "missing layers: " + ", ".join(missing),
        )
    message_hashes = {observation.message_hash for observation in observations}
    if len(message_hashes) != 1:
        _add(
            blockers,
            "MPR26_MESSAGE_HASH_DRIFT",
            "all economics must bind one exact message hash",
        )
    fixture_lineage = {
        Lineage.SYNTHETIC_FIXTURE,
        Lineage.RECORDED_PROVIDER_FIXTURE,
    }
    promotable_layers = {
        EconomicLayer.PAPER_ESTIMATED,
        EconomicLayer.FINALIZED_REALIZED,
    }
    for observation in observations:
        if observation.layer is EconomicLayer.PAPER_ESTIMATED:
            if observation.realized_claimed:
                _add(
                    blockers,
                    "MPR26_PAPER_REALIZED_CLAIM",
                    "paper outcome cannot claim realized PnL",
                )
        if observation.lineage in fixture_lineage:
            if observation.layer in promotable_layers:
                _add(
                    blockers,
                    "MPR26_FIXTURE_PROMOTION_FORBIDDEN",
                    "fixture lineage cannot promote paper/finalized economics",
                )


def _validate_settlement(
    evidence: MPR26Evidence, blockers: list[MPR26Blocker]
) -> None:
    settlement = evidence.settlement
    if settlement.ack_or_bundle_id_used_as_success:
        _add(
            blockers,
            "MPR26_ACK_USED_AS_SETTLEMENT",
            "ACK/bundle id is transport evidence only",
        )
    if settlement.landed_used_as_success:
        _add(
            blockers,
            "MPR26_LANDED_USED_AS_FINAL_ECONOMICS",
            "landed is not finalized economic proof",
        )
    if settlement.settlement_status is SettlementStatus.FINALIZED:
        missing = [
            name
            for name in (
                "finalized_transaction_hash",
                "payer_delta_hash",
                "token_delta_hash",
                "finality_slot",
            )
            if getattr(settlement, name) is None
        ]
        if missing:
            _add(
                blockers,
                "MPR26_FINALIZED_PROOF_INCOMPLETE",
                "missing: " + ", ".join(missing),
            )
    for observation in evidence.observations:
        if observation.layer is EconomicLayer.FINALIZED_REALIZED:
            if settlement.settlement_status is not SettlementStatus.FINALIZED:
                _add(
                    blockers,
                    "MPR26_REALIZED_WITHOUT_FINALITY",
                    "realized PnL requires finalized settlement",
                )
            if observation.message_hash != settlement.exact_message_hash:
                _add(
                    blockers,
                    "MPR26_FINALIZED_MESSAGE_HASH_MISMATCH",
                    "finalized economics must bind exact settlement message",
                )


def _validate_firewall(
    firewall: InstructionFirewallProof, blockers: list[MPR26Blocker]
) -> None:
    for name in (
        "no_unknown_writable_accounts",
        "no_unknown_signer_accounts",
        "no_hidden_tip_transfer",
        "no_compute_budget_mutation_after_simulation",
        "same_message_tip_policy",
    ):
        if getattr(firewall, name) is not True:
            _add(
                blockers,
                "MPR26_INSTRUCTION_FIREWALL_INCOMPLETE",
                f"{name} is required",
            )


def _validate_jito(
    jito: JitoSettlementSemantics, blockers: list[MPR26Blocker]
) -> None:
    for name in (
        "bundle_ack_transport_only",
        "bundle_landed_not_final_economics",
        "uncle_rebroadcast_classified",
        "tip_transaction_local_when_required",
        "finalized_reconciliation_required",
    ):
        if getattr(jito, name) is not True:
            _add(blockers, "MPR26_JITO_SEMANTICS_INCOMPLETE", f"{name} is required")


def _validate_lineage_policy(
    policy: LineageQuarantinePolicy, blockers: list[MPR26Blocker]
) -> None:
    for name in (
        "metrics_lineage_label_required",
        "paper_and_realized_pnl_separated",
        "synthetic_not_promotable",
        "recorded_fixture_not_promotable",
        "no_cross_lineage_aggregation_without_label",
    ):
        if getattr(policy, name) is not True:
            _add(
                blockers,
                "MPR26_LINEAGE_QUARANTINE_INCOMPLETE",
                f"{name} is required",
            )


def _add(blockers: list[MPR26Blocker], code: str, message: str) -> None:
    blockers.append(MPR26Blocker(code=code, message=message))


def _dedupe(blockers: Iterable[MPR26Blocker]) -> Iterable[MPR26Blocker]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key not in seen:
            seen.add(key)
            yield blocker


def _strict_int(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be a strict integer")


def _optional_sha(value: str | None, field_name: str) -> None:
    if value is not None:
        _sha(value, field_name)


def _sha(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be sha256 hex")


def _text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")


def _hash_dataclass(value: object) -> str:
    encoded = json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize(value: object) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _normalize(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple | list):
        return [_normalize(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _normalize(item) for key, item in value.items()}
    return value
