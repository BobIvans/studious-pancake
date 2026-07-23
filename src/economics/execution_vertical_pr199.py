"""PR-199 economic execution vertical contracts.

This module is sender-free. It turns a detected opportunity into one
mint-aware native/wSOL capital candidate, binds that candidate to immutable
planning, compilation, exact-simulation and reconciliation hashes, and refuses
to book paper profit unless the final message was simulated and reconciled with
the same identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from typing import Any, Mapping

from src.domain.money import NATIVE_SOL_MINT, WSOL_MINT
from src.economics.capital import (
    AtomicCapitalLedger,
    CapitalCandidate,
    CapitalDecision,
    CapitalPolicy,
    NativeCostBreakdown,
)

PR199_SCHEMA_VERSION = "pr199.economic-execution-vertical.v1"
_NATIVE_MINTS = frozenset({NATIVE_SOL_MINT, WSOL_MINT})
_HASH_LEN = 64


class PR199EconomicError(ValueError):
    """Raised when PR-199 economic evidence is malformed or unsafe."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PaperOutcome(StrEnum):
    BLOCKED = "blocked"
    PLANNED = "planned"
    SIMULATED_FAILURE = "simulated_failure"
    RECONCILED_PAPER_FAILURE = "reconciled_paper_failure"
    RECONCILED_PAPER_SUCCESS = "reconciled_paper_success"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class PR199PrecheckReport:
    allowed: bool
    reason_code: str
    details: Mapping[str, Any]
    candidate: CapitalCandidate | None = None
    decision: CapitalDecision | None = None


@dataclass(frozen=True, slots=True)
class EconomicIdentity:
    logical_opportunity_id: str
    attempt_generation: int
    evidence_generation_hash: str
    policy_hash: str
    route_hash: str
    plan_hash: str

    def __post_init__(self) -> None:
        if not self.logical_opportunity_id.strip():
            raise PR199EconomicError(
                "PR199_OPPORTUNITY_ID_MISSING", "opportunity id is required"
            )
        if self.attempt_generation < 1:
            raise PR199EconomicError(
                "PR199_ATTEMPT_GENERATION_INVALID",
                "attempt generation must be positive",
            )
        for field in (
            "evidence_generation_hash",
            "policy_hash",
            "route_hash",
            "plan_hash",
        ):
            _require_hash(getattr(self, field), field)

    @property
    def stable_key(self) -> str:
        payload = {
            "schema": PR199_SCHEMA_VERSION,
            "logical_opportunity_id": self.logical_opportunity_id,
            "attempt_generation": self.attempt_generation,
            "evidence_generation_hash": self.evidence_generation_hash,
            "policy_hash": self.policy_hash,
            "route_hash": self.route_hash,
            "plan_hash": self.plan_hash,
        }
        return _hash_json(payload)


@dataclass(frozen=True, slots=True)
class FinalMessageBinding:
    plan_hash: str
    compiled_message_hash: str
    blockhash_context_hash: str
    alt_evidence_hash: str
    account_metas_hash: str
    instruction_order_hash: str
    exact_simulation_hash: str
    exact_simulation_message_hash: str
    final_fee_hash: str

    def __post_init__(self) -> None:
        for field in self.__dataclass_fields__:
            _require_hash(getattr(self, field), field)
        if self.compiled_message_hash != self.exact_simulation_message_hash:
            raise PR199EconomicError(
                "PR199_SIMULATION_MESSAGE_HASH_MISMATCH",
                "exact simulation must use the compiled final message",
            )

    def assert_unchanged_for_permit(self, *, permit_message_hash: str) -> None:
        _require_hash(permit_message_hash, "permit_message_hash")
        if permit_message_hash != self.compiled_message_hash:
            raise PR199EconomicError(
                "PR199_PERMIT_MESSAGE_HASH_MISMATCH",
                "modified message cannot be authorized after simulation",
            )


@dataclass(frozen=True, slots=True)
class ImmutablePaperReconciliation:
    identity: EconomicIdentity
    capital_decision: CapitalDecision
    final_message: FinalMessageBinding
    simulated_net_profit_lamports: int
    conservative_net_profit_lamports: int
    reconciliation_hash: str
    outcome: PaperOutcome
    finalized_live_hash: str | None = None

    def __post_init__(self) -> None:
        if not self.capital_decision.allowed:
            raise PR199EconomicError(
                "PR199_RECONCILIATION_WITHOUT_RESERVATION",
                "paper reconciliation requires an allowed capital decision",
            )
        _require_hash(self.reconciliation_hash, "reconciliation_hash")
        if self.finalized_live_hash is not None:
            _require_hash(self.finalized_live_hash, "finalized_live_hash")
            raise PR199EconomicError(
                "PR199_FINALIZED_LIVE_DATA_FORBIDDEN_IN_PAPER",
                "paper accounting cannot book landed/finalized live evidence",
            )
        if self.conservative_net_profit_lamports < 0:
            object.__setattr__(
                self,
                "outcome",
                PaperOutcome.RECONCILED_PAPER_FAILURE,
            )
        if self.outcome is PaperOutcome.RECONCILED_PAPER_SUCCESS:
            if self.simulated_net_profit_lamports <= 0:
                raise PR199EconomicError(
                    "PR199_SUCCESS_REQUIRES_POSITIVE_SIMULATED_NET",
                    "paper success requires positive simulated net profit",
                )
            if self.conservative_net_profit_lamports <= 0:
                raise PR199EconomicError(
                    "PR199_SUCCESS_REQUIRES_POSITIVE_CONSERVATIVE_NET",
                    "paper success requires positive conservative net profit",
                )

    @property
    def accounting_hash(self) -> str:
        return _hash_json(
            {
                "schema": PR199_SCHEMA_VERSION,
                "identity": self.identity.stable_key,
                "capital": self.capital_decision.to_json(),
                "message_hash": self.final_message.compiled_message_hash,
                "simulation_hash": self.final_message.exact_simulation_hash,
                "simulated_net_profit_lamports": str(
                    self.simulated_net_profit_lamports
                ),
                "conservative_net_profit_lamports": str(
                    self.conservative_net_profit_lamports
                ),
                "reconciliation_hash": self.reconciliation_hash,
                "outcome": self.outcome.value,
                "finalized_live_hash": self.finalized_live_hash,
            }
        )


def assess_shadow_opportunity_pr199(
    opportunity: Any,
    config: Any,
    *,
    wallet_lamports: int | None = None,
) -> PR199PrecheckReport:
    """Replace gross-only shadow precheck with a mint/cost-bound gate."""

    metadata = getattr(opportunity, "metadata", {}) or {}
    monetary = getattr(config, "monetary", None)
    minimum_profit = _int_config(monetary, "minimum_net_profit_lamports", 0)
    contingency = _int_config(monetary, "contingency_lamports", 0)
    gross_profit = _metadata_int(metadata, "gross_profit_base_units", 0)
    required_edge = minimum_profit + contingency
    base_details: dict[str, Any] = {
        "schema_version": PR199_SCHEMA_VERSION,
        "gross_profit_base_units": gross_profit,
        "minimum_net_profit_lamports": minimum_profit,
        "contingency_lamports": contingency,
        "required_edge_lamports": required_edge,
    }
    if gross_profit <= required_edge:
        return PR199PrecheckReport(
            allowed=False,
            reason_code="no_trade_insufficient_prechecked_edge",
            details=base_details,
        )

    try:
        candidate = candidate_from_shadow_opportunity(opportunity, metadata)
    except PR199EconomicError as exc:
        return PR199PrecheckReport(
            allowed=False,
            reason_code=exc.code.lower(),
            details={**base_details, "error_code": exc.code},
        )

    policy = CapitalPolicy.from_runtime_config(config)
    ledger = AtomicCapitalLedger(
        wallet_lamports=(
            _int_config(monetary, "wallet_lamports", 0)
            if wallet_lamports is None
            else wallet_lamports
        ),
        policy=policy,
    )
    decision = ledger.evaluate(candidate)
    details = {
        **base_details,
        **decision.to_json(),
        "input_mint": getattr(opportunity, "input_mint", None),
        "settlement_mint": getattr(opportunity, "output_mint", None),
        "projected_final_base_units": str(candidate.guaranteed_min_out_lamports),
        "flash_repayment_lamports": str(candidate.flash_repayment_lamports),
        "settled_native_cost_lamports": str(
            candidate.native_costs.settled_native_cost_lamports()
        ),
        "economic_gate": "pr199_mint_cost_bound_capital_gate",
    }
    if not decision.allowed:
        return PR199PrecheckReport(
            allowed=False,
            reason_code=f"no_trade_{decision.reason.value}",
            details=details,
            candidate=candidate,
            decision=decision,
        )
    return PR199PrecheckReport(
        allowed=True,
        reason_code="capital_precheck_passed",
        details=details,
        candidate=candidate,
        decision=decision,
    )


def candidate_from_shadow_opportunity(
    opportunity: Any,
    metadata: Mapping[str, Any],
) -> CapitalCandidate:
    input_mint = str(getattr(opportunity, "input_mint", ""))
    output_mint = str(getattr(opportunity, "output_mint", ""))
    if input_mint != output_mint or input_mint not in _NATIVE_MINTS:
        raise PR199EconomicError(
            "PR199_NATIVE_SETTLEMENT_REQUIRED",
            "shadow economic gate requires native/wSOL circular settlement",
        )
    required = (
        "base_network_fee_lamports",
        "priority_fee_lamports",
        "jito_tip_lamports",
        "peak_rent_lamports",
        "rent_loss_lamports",
        "protocol_fee_lamports",
        "slippage_buffer_lamports",
        "uncertainty_buffer_lamports",
    )
    missing = [name for name in required if name not in metadata]
    if missing:
        raise PR199EconomicError(
            "PR199_COST_EVIDENCE_MISSING",
            "gross edge requires complete fee/rent/tip/protocol cost evidence",
        )
    requested = int(getattr(opportunity, "proposed_amount_base_units", 0))
    if requested <= 0:
        raise PR199EconomicError(
            "PR199_REQUESTED_AMOUNT_INVALID", "requested amount must be positive"
        )
    projected_final = _metadata_int(metadata, "projected_final_base_units", 0)
    if projected_final <= 0:
        raise PR199EconomicError(
            "PR199_PROJECTED_FINAL_AMOUNT_MISSING",
            "projected final base units are required",
        )
    return CapitalCandidate(
        candidate_id=str(getattr(opportunity, "opportunity_id", "")),
        guaranteed_min_out_lamports=projected_final,
        flash_repayment_lamports=_metadata_int(
            metadata,
            "flash_repayment_lamports",
            requested,
        ),
        requested_flash_loan_lamports=requested,
        native_costs=NativeCostBreakdown(
            base_network_fee_lamports=_metadata_int(
                metadata,
                "base_network_fee_lamports",
            ),
            priority_fee_lamports=_metadata_int(metadata, "priority_fee_lamports"),
            jito_tip_lamports=_metadata_int(metadata, "jito_tip_lamports"),
            peak_rent_lamports=_metadata_int(metadata, "peak_rent_lamports"),
            rent_loss_lamports=_metadata_int(metadata, "rent_loss_lamports"),
        ),
        protocol_fee_lamports=_metadata_int(metadata, "protocol_fee_lamports"),
        slippage_buffer_lamports=_metadata_int(metadata, "slippage_buffer_lamports"),
        uncertainty_buffer_lamports=_metadata_int(
            metadata,
            "uncertainty_buffer_lamports",
        ),
        message_hash=_optional_metadata_hash(metadata, "message_hash"),
    )


def _int_config(source: Any, field: str, default: int) -> int:
    value = getattr(source, field, default)
    return _strict_int(value, field)


def _metadata_int(
    metadata: Mapping[str, Any],
    field: str,
    default: int | None = None,
) -> int:
    if field not in metadata:
        if default is None:
            raise PR199EconomicError(
                "PR199_COST_EVIDENCE_MISSING", f"{field} is required"
            )
        return default
    return _strict_int(metadata[field], field)


def _strict_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or isinstance(value, float):
        raise PR199EconomicError(
            "PR199_INTEGER_UNITS_REQUIRED", f"{field} must be integer base units"
        )
    try:
        integer = int(value)
    except (TypeError, ValueError) as exc:
        raise PR199EconomicError(
            "PR199_INTEGER_UNITS_REQUIRED", f"{field} must be integer base units"
        ) from exc
    if integer < 0:
        raise PR199EconomicError(
            "PR199_NON_NEGATIVE_UNITS_REQUIRED", f"{field} cannot be negative"
        )
    return integer


def _optional_metadata_hash(metadata: Mapping[str, Any], field: str) -> str | None:
    value = metadata.get(field)
    if value is None:
        return None
    text = str(value)
    _require_hash(text, field)
    return text


def _require_hash(value: str, field: str) -> None:
    if len(value) != _HASH_LEN or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise PR199EconomicError(
            "PR199_HASH_INVALID", f"{field} must be lower-case SHA-256 hex"
        )


def _hash_json(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
