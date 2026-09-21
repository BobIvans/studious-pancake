"""PR-272 / PERF-02: safe vectorized quote/state research."""
from __future__ import annotations

from typing import Mapping, Sequence

from .core import Mega807Error, require_nonnegative, require_positive


def vectorize_quote_surface(
    amounts: Sequence[int],
    rates_ppm: Sequence[int],
) -> tuple[tuple[int, ...], ...]:
    if not amounts or not rates_ppm:
        raise Mega807Error("VECTOR_SURFACE_EMPTY")
    return tuple(
        tuple(
            require_positive(amount, "amount")
            * require_nonnegative(rate, "rate_ppm")
            // 1_000_000
            for rate in rates_ppm
        )
        for amount in amounts
    )


def batch_route_state_transitions(
    branches: Sequence[Mapping[str, int]],
    deltas: Sequence[Mapping[str, int]],
) -> tuple[dict[str, int], ...]:
    if len(branches) != len(deltas):
        raise Mega807Error("BATCH_STATE_LENGTH_MISMATCH")
    out: list[dict[str, int]] = []
    for state, change in zip(branches, deltas, strict=True):
        row = {key: require_nonnegative(value, key) for key, value in state.items()}
        for key, delta in change.items():
            if isinstance(delta, bool) or not isinstance(delta, int):
                raise Mega807Error("STATE_DELTA_NOT_INTEGER")
            updated = row.get(key, 0) + delta
            if updated < 0:
                raise Mega807Error("BATCH_STATE_UNDERFLOW")
            row[key] = updated
        out.append(row)
    return tuple(out)


def benchmark_vectorized_solver(
    *, scalar_work_units: int, vector_work_units: int, same_outputs: bool
) -> dict[str, int | bool]:
    scalar = require_positive(scalar_work_units, "scalar_work_units")
    vector = require_positive(vector_work_units, "vector_work_units")
    if not same_outputs:
        raise Mega807Error("VECTOR_PARITY_REQUIRED")
    return {
        "scalar_work_units": scalar,
        "vector_work_units": vector,
        "saved_work_units": max(0, scalar - vector),
        "same_outputs": True,
    }


def fall_back_to_scalar_reference(
    *, supported_semantics: bool, scalar_result: Sequence[int]
) -> tuple[int, ...]:
    if supported_semantics:
        raise Mega807Error("FALLBACK_ONLY_FOR_UNSUPPORTED_SEMANTICS")
    return tuple(require_nonnegative(value, "scalar_result") for value in scalar_result)
