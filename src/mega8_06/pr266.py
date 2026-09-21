"""PR-266 / SUBMIT-03: evidence-driven transport selection, no sending."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega806Error, require_nonnegative_int, require_ppm, require_text


def register_submission_transport(
    *,
    name: str,
    generation: str,
    qualified: bool,
    supports_private_path: bool = False,
) -> dict[str, object]:
    return {
        "name": require_text(name, "name"),
        "generation": require_text(generation, "generation"),
        "qualified": bool(qualified),
        "supports_private_path": bool(supports_private_path),
        "submission_authority": False,
    }


def score_transport_inclusion(
    *,
    inclusion_ppm: int,
    expected_cost: int,
    ambiguity_ppm: int,
) -> int:
    inclusion_ppm = require_ppm(inclusion_ppm, "inclusion_ppm")
    expected_cost = require_nonnegative_int(expected_cost, "expected_cost")
    ambiguity_ppm = require_ppm(ambiguity_ppm, "ambiguity_ppm")
    cost_penalty = min(1_000_000, expected_cost)
    return max(0, inclusion_ppm - ambiguity_ppm - cost_penalty)


def route_submission_variant(
    transports: Sequence[Mapping[str, object]],
    metrics: Mapping[str, Mapping[str, int]],
) -> str:
    scored = []
    for transport in transports:
        if transport.get("qualified") is not True:
            continue
        name = require_text(transport.get("name"), "name")
        row = metrics.get(name)
        if row is None:
            continue
        score = score_transport_inclusion(
            inclusion_ppm=row.get("inclusion_ppm", 0),
            expected_cost=row.get("expected_cost", 0),
            ambiguity_ppm=row.get("ambiguity_ppm", 1_000_000),
        )
        scored.append((score, name))
    if not scored:
        raise Mega806Error("NO_QUALIFIED_TRANSPORT")
    return max(scored, key=lambda item: (item[0], item[1]))[1]


def reconcile_transport_receipts(
    receipts: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    ids = tuple(
        sorted(require_text(row.get("receipt_id"), "receipt_id") for row in receipts)
    )
    settled = [row for row in receipts if row.get("finalized") is True]
    return {
        "receipt_ids": ids,
        "advisory_only": True,
        "finalized_count": len(settled),
        "unknown_outcome": bool(receipts) and not settled,
    }
