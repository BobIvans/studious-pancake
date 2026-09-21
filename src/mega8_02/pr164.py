"""PR-164 / GRAPH-03: deterministic operation hyperedges."""
from __future__ import annotations
from typing import Mapping, Sequence
from .core import Hyperedge, Mega802Error, apply_hyperedge_core, compile_hyperedge_core


def compile_operation_hyperedge(
    *, edge_id: str, inputs: Mapping[str, int], outputs: Mapping[str, int],
    obligations: Mapping[str, int] | None = None,
    writable_resources: Sequence[str] = (),
) -> Hyperedge:
    return compile_hyperedge_core(
        edge_id=edge_id, inputs=inputs, outputs=outputs,
        obligations=obligations, writable_resources=writable_resources,
    )


def bind_multi_input_obligations(
    edge: Hyperedge, required: Mapping[str, int]
) -> Hyperedge:
    merged = dict(edge.obligations)
    for asset, amount in required.items():
        if amount <= 0:
            raise Mega802Error("INVALID_OBLIGATION")
        merged[asset] = merged.get(asset, 0) + amount
    return compile_hyperedge_core(
        edge_id=edge.edge_id, inputs=dict(edge.inputs), outputs=dict(edge.outputs),
        obligations=merged, writable_resources=edge.writable_resources,
    )


def value_multi_output_residuals(
    outputs: Mapping[str, int], prices_ppm: Mapping[str, int]
) -> int:
    value = 0
    for asset, amount in outputs.items():
        if amount < 0 or prices_ppm.get(asset, 0) < 0:
            raise Mega802Error("INVALID_RESIDUAL_VALUE")
        if asset not in prices_ppm:
            raise Mega802Error("MISSING_RESIDUAL_PRICE")
        value += amount * prices_ppm[asset] // 1_000_000
    return value


def simulate_hyperedge_state_transition(
    state: Mapping[str, int], edge: Hyperedge
) -> dict[str, int]:
    return apply_hyperedge_core(state, edge)
