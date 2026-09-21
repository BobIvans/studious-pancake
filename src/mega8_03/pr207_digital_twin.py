"""PR-207 / TWIN-01 — synthetic scenario provenance and sim-to-real calibration."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .common import PPM, integer, mean_int, stable_hash


def generate_synthetic_market_scenario(
    base_state: Mapping[str, int],
    shocks: Mapping[str, int],
    *,
    scenario_id: str,
) -> dict[str, Any]:
    state = {key: integer(value, f"base:{key}") for key, value in base_state.items()}
    for key, shock in shocks.items():
        state[key] = state.get(key, 0) + integer(shock, f"shock:{key}")
    payload = {
        "scenario_id": str(scenario_id),
        "state": state,
        "shocks": {key: integer(value, f"shock:{key}") for key, value in shocks.items()},
        "synthetic": True,
        "realized_pnl_eligible": False,
    }
    return payload | {"scenario_sha256": stable_hash("mega8-03/synthetic-scenario/v1", payload)}


def calibrate_digital_twin(
    simulated: Sequence[int],
    observed: Sequence[int],
) -> dict[str, int]:
    if not simulated or len(simulated) != len(observed):
        raise ValueError("simulated/observed arrays must align")
    errors = [
        abs(integer(sim, "simulated") - integer(obs, "observed"))
        for sim, obs in zip(simulated, observed, strict=True)
    ]
    scale = max(1, mean_int([abs(integer(value, "observed")) for value in observed]))
    return {
        "mean_absolute_gap": mean_int(errors),
        "relative_gap_ppm": mean_int(errors) * PPM // scale,
    }


def validate_sim_to_real_gap(
    calibration: Mapping[str, int],
    *,
    maximum_gap_ppm: int,
) -> dict[str, int | bool]:
    gap = integer(calibration["relative_gap_ppm"], "relative_gap_ppm", minimum=0)
    cap = integer(maximum_gap_ppm, "maximum_gap_ppm", minimum=0)
    return {"calibrated_for_research": gap <= cap, "relative_gap_ppm": gap}


def label_synthetic_vs_observed(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    labeled: list[dict[str, Any]] = []
    for row in rows:
        source = str(row.get("source_kind", "")).lower()
        if source not in {"synthetic", "observed"}:
            raise ValueError("source_kind must be synthetic or observed")
        labeled.append(dict(row) | {"synthetic": source == "synthetic", "realized_pnl_eligible": source == "observed"})
    return tuple(labeled)


__all__ = [
    "calibrate_digital_twin",
    "generate_synthetic_market_scenario",
    "label_synthetic_vs_observed",
    "validate_sim_to_real_gap",
]
