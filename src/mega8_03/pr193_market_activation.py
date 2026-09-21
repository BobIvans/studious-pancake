"""PR-193 / LISTING-01 — verified new-market lifecycle and coverage research."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .common import EvidenceEnvelope, OfflineDecision, decision, integer, require_rows


def detect_new_market_activation(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    require_rows(rows, "market_events")
    events = [
        dict(row)
        for row in rows
        if row.get("deployment_verified") is True
        and row.get("active") is True
        and str(row.get("market_id", "")).strip()
    ]
    return tuple(
        sorted(
            events,
            key=lambda row: (
                integer(row.get("available_at_ns", 0), "available_at_ns", minimum=0),
                str(row["market_id"]),
            ),
        )
    )


def compare_router_direct_coverage(
    *,
    router_market_ids: Sequence[str],
    direct_market_ids: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    router = {str(item) for item in router_market_ids if str(item)}
    direct = {str(item) for item in direct_market_ids if str(item)}
    return {
        "direct_only": tuple(sorted(direct - router)),
        "router_only": tuple(sorted(router - direct)),
        "shared": tuple(sorted(router & direct)),
    }


def verify_liquid_exit_path(
    *,
    exit_capacity_atomic: int,
    required_exit_atomic: int,
    quote_current: bool,
    token_semantics_verified: bool,
) -> dict[str, Any]:
    capacity = integer(exit_capacity_atomic, "exit_capacity_atomic", minimum=0)
    required = integer(required_exit_atomic, "required_exit_atomic", minimum=1)
    return {
        "exit_capacity_atomic": capacity,
        "required_exit_atomic": required,
        "verified": capacity >= required and quote_current and token_semantics_verified,
    }


def qualify_new_market_worker(
    *,
    envelope: EvidenceEnvelope,
    coverage: Mapping[str, Any],
    exit_path: Mapping[str, Any],
    direct_adapter_qualified: bool,
) -> OfflineDecision:
    reasons: list[str] = []
    if exit_path.get("verified") is not True:
        reasons.append("NO_LIQUID_EXIT")
    if direct_adapter_qualified is not True:
        reasons.append("DIRECT_ADAPTER_UNQUALIFIED")
    payload = {
        "coverage": dict(coverage),
        "exit_path": dict(exit_path),
        "direct_adapter_qualified": bool(direct_adapter_qualified),
    }
    return decision(
        "PR-193",
        envelope=envelope,
        payload=payload,
        reasons=reasons,
        research_only=True,
    )


__all__ = [
    "compare_router_direct_coverage",
    "detect_new_market_activation",
    "qualify_new_market_worker",
    "verify_liquid_exit_path",
]
