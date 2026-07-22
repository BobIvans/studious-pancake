"""PR-128 compute-budget, loaded-data and landing-cost finalization.

The helpers in this module are intentionally offline and fail-closed. They turn
simulation/provider observations into an explicit Solana Compute Budget
instruction set before an exact final message is eligible for fee quoting,
permit binding, or later submission.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from solders.compute_budget import (
    set_compute_unit_limit,
    set_compute_unit_price,
    set_loaded_accounts_data_size_limit,
)
from solders.instruction import Instruction

from .models import COMPUTE_BUDGET_PROGRAM_ID

MAX_COMPUTE_UNIT_LIMIT = 1_400_000
MAX_LOADED_ACCOUNTS_DATA_SIZE_BYTES = 64 * 1024 * 1024
_COMPUTE_BUDGET_VARIANTS = frozenset({1, 2, 3, 4})


class ComputeBudgetFinalizationCode(StrEnum):
    """Redacted PR-128 failure taxonomy."""

    INVALID_OBSERVATION = "invalid-observation"
    LOADED_ACCOUNT_DATA_UNAVAILABLE = "loaded-account-data-unavailable"
    PRIORITY_FEE_EVIDENCE_UNAVAILABLE = "priority-fee-evidence-unavailable"
    PRIORITY_FEE_EVIDENCE_STALE = "priority-fee-evidence-stale"
    PRIORITY_FEE_CAP_EXCEEDED = "priority-fee-cap-exceeded"
    LANDING_COST_CAP_EXCEEDED = "landing-cost-cap-exceeded"
    COMPUTE_BUDGET_DUPLICATE = "compute-budget-duplicate"
    FINAL_OBSERVATION_MISMATCH = "final-observation-mismatch"


class ComputeBudgetFinalizationError(ValueError):
    """Typed fail-closed error for compute/fee finalization."""

    def __init__(
        self,
        code: ComputeBudgetFinalizationCode,
        message: str,
        *,
        details: dict[str, int | str | None] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class PriorityFeeObservation:
    """Sanitized getRecentPrioritizationFees-derived evidence."""

    slot: int
    micro_lamports_per_cu: int
    writable_accounts: tuple[str, ...]
    endpoint_id: str
    source: str = "getRecentPrioritizationFees"


@dataclass(frozen=True, slots=True)
class FinalComputeBudgetPolicy:
    """Explicit final compute budget and fee-market decision."""

    unit_limit: int
    micro_lamports_per_cu: int
    loaded_accounts_data_size_limit: int
    observed_units_consumed: int
    observed_loaded_accounts_data_size: int
    priority_fee_slot: int
    priority_fee_endpoint_id: str
    expected_network_fee_lamports: int
    tip_lamports: int = 0
    max_total_landing_cost_lamports: int | None = None

    @property
    def total_landing_cost_lamports(self) -> int:
        return self.expected_network_fee_lamports + self.tip_lamports


@dataclass(frozen=True, slots=True)
class FinalObservation:
    """Final exact-message observation that must match the approved policy."""

    units_consumed: int
    loaded_accounts_data_size: int
    network_fee_lamports: int


def finalize_compute_budget_policy(
    *,
    observed_units_consumed: int,
    observed_loaded_accounts_data_size: int | None,
    priority_fee_observations: Sequence[PriorityFeeObservation],
    min_context_slot: int,
    expected_network_fee_lamports: int,
    tip_lamports: int = 0,
    compute_margin_bps: int = 12_000,
    loaded_data_margin_bps: int = 12_000,
    priority_fee_percentile_bps: int = 7_500,
    max_micro_lamports_per_cu: int | None = None,
    max_total_landing_cost_lamports: int | None = None,
    max_compute_unit_limit: int = MAX_COMPUTE_UNIT_LIMIT,
    max_loaded_accounts_data_size: int = MAX_LOADED_ACCOUNTS_DATA_SIZE_BYTES,
) -> FinalComputeBudgetPolicy:
    """Build an explicit final compute/fee policy from bounded observations."""

    units = _require_positive_int(
        observed_units_consumed,
        "observed_units_consumed",
        ComputeBudgetFinalizationCode.INVALID_OBSERVATION,
    )
    if observed_loaded_accounts_data_size is None:
        raise ComputeBudgetFinalizationError(
            ComputeBudgetFinalizationCode.LOADED_ACCOUNT_DATA_UNAVAILABLE,
            "loadedAccountsDataSize is required for PR-128 finalization",
        )
    loaded = _require_positive_int(
        observed_loaded_accounts_data_size,
        "observed_loaded_accounts_data_size",
        ComputeBudgetFinalizationCode.INVALID_OBSERVATION,
        allow_zero=True,
    )
    network_fee = _require_positive_int(
        expected_network_fee_lamports,
        "expected_network_fee_lamports",
        ComputeBudgetFinalizationCode.INVALID_OBSERVATION,
        allow_zero=True,
    )
    tip = _require_positive_int(
        tip_lamports,
        "tip_lamports",
        ComputeBudgetFinalizationCode.INVALID_OBSERVATION,
        allow_zero=True,
    )
    if min_context_slot < 0:
        raise ComputeBudgetFinalizationError(
            ComputeBudgetFinalizationCode.INVALID_OBSERVATION,
            "min_context_slot must be non-negative",
        )

    unit_limit = _bounded_margin(
        units,
        compute_margin_bps,
        floor=1,
        ceiling=max_compute_unit_limit,
        label="compute unit limit",
    )
    loaded_limit = _bounded_margin(
        max(loaded, 1),
        loaded_data_margin_bps,
        floor=1,
        ceiling=max_loaded_accounts_data_size,
        label="loaded account data size limit",
    )
    fee_price, fee_slot, endpoint_id = _select_priority_fee(
        priority_fee_observations,
        min_context_slot=min_context_slot,
        percentile_bps=priority_fee_percentile_bps,
        max_micro_lamports_per_cu=max_micro_lamports_per_cu,
    )
    total_landing_cost = network_fee + tip
    if (
        max_total_landing_cost_lamports is not None
        and total_landing_cost > max_total_landing_cost_lamports
    ):
        raise ComputeBudgetFinalizationError(
            ComputeBudgetFinalizationCode.LANDING_COST_CAP_EXCEEDED,
            "total landing cost exceeds policy cap",
            details={
                "actual": total_landing_cost,
                "limit": max_total_landing_cost_lamports,
            },
        )

    return FinalComputeBudgetPolicy(
        unit_limit=unit_limit,
        micro_lamports_per_cu=fee_price,
        loaded_accounts_data_size_limit=loaded_limit,
        observed_units_consumed=units,
        observed_loaded_accounts_data_size=loaded,
        priority_fee_slot=fee_slot,
        priority_fee_endpoint_id=endpoint_id,
        expected_network_fee_lamports=network_fee,
        tip_lamports=tip,
        max_total_landing_cost_lamports=max_total_landing_cost_lamports,
    )


def build_compute_budget_instructions(
    policy: FinalComputeBudgetPolicy,
) -> tuple[Instruction, ...]:
    """Return exactly one final instruction for each PR-128 budget dimension."""

    instructions = (
        set_compute_unit_limit(policy.unit_limit),
        set_compute_unit_price(policy.micro_lamports_per_cu),
        set_loaded_accounts_data_size_limit(policy.loaded_accounts_data_size_limit),
    )
    assert_single_compute_budget_variants(instructions)
    return instructions


def assert_single_compute_budget_variants(instructions: Iterable[Instruction]) -> None:
    """Reject duplicate or malformed Compute Budget variants before message build."""

    seen: dict[int, int] = {}
    for index, instruction in enumerate(instructions):
        if instruction.program_id != COMPUTE_BUDGET_PROGRAM_ID:
            continue
        if not instruction.data:
            raise ComputeBudgetFinalizationError(
                ComputeBudgetFinalizationCode.INVALID_OBSERVATION,
                "empty compute budget instruction data",
                details={"index": index},
            )
        variant = instruction.data[0]
        if variant not in _COMPUTE_BUDGET_VARIANTS:
            raise ComputeBudgetFinalizationError(
                ComputeBudgetFinalizationCode.INVALID_OBSERVATION,
                "unknown compute budget instruction variant",
                details={"index": index, "variant": variant},
            )
        if variant in seen:
            raise ComputeBudgetFinalizationError(
                ComputeBudgetFinalizationCode.COMPUTE_BUDGET_DUPLICATE,
                "duplicate compute budget instruction variant",
                details={"first_index": seen[variant], "duplicate_index": index},
            )
        seen[variant] = index


def validate_final_observation(
    policy: FinalComputeBudgetPolicy,
    observation: FinalObservation,
) -> None:
    """Verify final exact-message simulation/fee observation matches policy."""

    if observation.units_consumed > policy.unit_limit:
        raise ComputeBudgetFinalizationError(
            ComputeBudgetFinalizationCode.FINAL_OBSERVATION_MISMATCH,
            "final simulation consumed more CU than approved limit",
        )
    if observation.loaded_accounts_data_size > policy.loaded_accounts_data_size_limit:
        raise ComputeBudgetFinalizationError(
            ComputeBudgetFinalizationCode.FINAL_OBSERVATION_MISMATCH,
            "final simulation loaded more account data than approved limit",
        )
    if observation.network_fee_lamports != policy.expected_network_fee_lamports:
        raise ComputeBudgetFinalizationError(
            ComputeBudgetFinalizationCode.FINAL_OBSERVATION_MISMATCH,
            "final fee does not match approved getFeeForMessage result",
        )
    if (
        policy.max_total_landing_cost_lamports is not None
        and observation.network_fee_lamports + policy.tip_lamports
        > policy.max_total_landing_cost_lamports
    ):
        raise ComputeBudgetFinalizationError(
            ComputeBudgetFinalizationCode.LANDING_COST_CAP_EXCEEDED,
            "observed landing cost exceeds approved cap",
        )


def _select_priority_fee(
    observations: Sequence[PriorityFeeObservation],
    *,
    min_context_slot: int,
    percentile_bps: int,
    max_micro_lamports_per_cu: int | None,
) -> tuple[int, int, str]:
    if not 0 <= percentile_bps <= 10_000:
        raise ComputeBudgetFinalizationError(
            ComputeBudgetFinalizationCode.INVALID_OBSERVATION,
            "priority fee percentile must be in basis points",
        )
    usable: list[PriorityFeeObservation] = []
    for observation in observations:
        if observation.slot < min_context_slot:
            continue
        _require_positive_int(
            observation.micro_lamports_per_cu,
            "micro_lamports_per_cu",
            ComputeBudgetFinalizationCode.INVALID_OBSERVATION,
            allow_zero=True,
        )
        usable.append(observation)
    if not observations:
        raise ComputeBudgetFinalizationError(
            ComputeBudgetFinalizationCode.PRIORITY_FEE_EVIDENCE_UNAVAILABLE,
            "priority fee evidence is required",
        )
    if not usable:
        raise ComputeBudgetFinalizationError(
            ComputeBudgetFinalizationCode.PRIORITY_FEE_EVIDENCE_STALE,
            "priority fee evidence is below minContextSlot",
        )
    ordered = sorted(usable, key=lambda item: item.micro_lamports_per_cu)
    index = ((len(ordered) - 1) * percentile_bps + 9_999) // 10_000
    selected = ordered[index]
    if (
        max_micro_lamports_per_cu is not None
        and selected.micro_lamports_per_cu > max_micro_lamports_per_cu
    ):
        raise ComputeBudgetFinalizationError(
            ComputeBudgetFinalizationCode.PRIORITY_FEE_CAP_EXCEEDED,
            "priority fee price exceeds policy cap",
            details={
                "actual": selected.micro_lamports_per_cu,
                "limit": max_micro_lamports_per_cu,
            },
        )
    return selected.micro_lamports_per_cu, selected.slot, selected.endpoint_id


def _bounded_margin(
    value: int,
    margin_bps: int,
    *,
    floor: int,
    ceiling: int,
    label: str,
) -> int:
    if margin_bps < 10_000:
        raise ComputeBudgetFinalizationError(
            ComputeBudgetFinalizationCode.INVALID_OBSERVATION,
            f"{label} margin must be at least 1.0x",
        )
    if ceiling < floor:
        raise ComputeBudgetFinalizationError(
            ComputeBudgetFinalizationCode.INVALID_OBSERVATION,
            f"{label} bounds are invalid",
        )
    scaled = (value * margin_bps + 9_999) // 10_000
    return min(ceiling, max(floor, scaled))


def _require_positive_int(
    value: int,
    label: str,
    code: ComputeBudgetFinalizationCode,
    *,
    allow_zero: bool = False,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ComputeBudgetFinalizationError(code, f"{label} must be an integer")
    if value < 0 or (value == 0 and not allow_zero):
        raise ComputeBudgetFinalizationError(code, f"{label} must be positive")
    return value


__all__ = [
    "ComputeBudgetFinalizationCode",
    "ComputeBudgetFinalizationError",
    "FinalComputeBudgetPolicy",
    "FinalObservation",
    "PriorityFeeObservation",
    "assert_single_compute_budget_variants",
    "build_compute_budget_instructions",
    "finalize_compute_budget_policy",
    "validate_final_observation",
]
