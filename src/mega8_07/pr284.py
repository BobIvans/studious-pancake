"""PR-284 / STABLE-02: reserve, redemption and depeg stress research."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .core import EvidenceBinding, Mega807Error, require_nonnegative, stable_hash


@dataclass(frozen=True, slots=True)
class StablecoinReserveModel:
    asset_id: str
    reserve_components: Mapping[str, int]
    redemption_capacity: int
    queue_depth: int
    evidence: EvidenceBinding


def register_stablecoin_reserve_model(
    model: StablecoinReserveModel, *, now: int
) -> str:
    model.evidence.assert_usable(now=now)
    if not model.reserve_components:
        raise Mega807Error("STABLECOIN_RESERVES_REQUIRED")
    for name, value in model.reserve_components.items():
        require_nonnegative(value, name)
    return stable_hash(
        "mega8-07-stablecoin-reserve",
        {
            "asset": model.asset_id,
            "reserves": dict(sorted(model.reserve_components.items())),
            "evidence": model.evidence.identity,
        },
    )


def ingest_redemption_capacity(
    model: StablecoinReserveModel, *, now: int
) -> tuple[int, int]:
    model.evidence.assert_usable(now=now)
    return (
        require_nonnegative(model.redemption_capacity, "redemption_capacity"),
        require_nonnegative(model.queue_depth, "queue_depth"),
    )


def stress_stablecoin_run(
    model: StablecoinReserveModel, *, redemption_demand: int, reserve_haircut_ppm: int
) -> dict[str, int | bool]:
    demand = require_nonnegative(redemption_demand, "redemption_demand")
    haircut = require_nonnegative(reserve_haircut_ppm, "reserve_haircut_ppm")
    if haircut > 1_000_000:
        raise Mega807Error("INVALID_RESERVE_HAIRCUT")
    reserves = sum(model.reserve_components.values())
    stressed = reserves * (1_000_000 - haircut) // 1_000_000
    executable = min(model.redemption_capacity, stressed)
    return {
        "stressed_reserves": stressed,
        "executable_redemption": executable,
        "unmet_demand": max(0, demand - executable),
        "queue_stressed": demand > executable,
    }


def emit_depeg_risk_signal(
    stress: Mapping[str, int | bool], *, signal_threshold: int
) -> dict[str, int | bool]:
    unmet = int(stress.get("unmet_demand", 0))
    return {
        "risk_signal": unmet >= signal_threshold,
        "unmet_demand": unmet,
        "trade_authority": False,
    }
