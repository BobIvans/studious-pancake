"""PR-188 / RFQ-01 — opt-in RFQ and limit-order fill research contracts."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .common import EvidenceEnvelope, OfflineDecision, decision, integer, require_rows, stable_hash


def ingest_solana_intent_quotes(
    rows: Sequence[Mapping[str, Any]],
    *,
    now_ns: int,
) -> tuple[dict[str, Any], ...]:
    require_rows(rows, "intent_quotes")
    now = integer(now_ns, "now_ns", minimum=0)
    accepted: list[dict[str, Any]] = []
    for row in rows:
        if row.get("opt_in") is not True:
            continue
        expires = integer(row.get("expires_at_ns", 0), "expires_at_ns", minimum=0)
        if expires <= now:
            continue
        intent_id = str(row.get("intent_id", "")).strip()
        quote_id = str(row.get("quote_id", "")).strip()
        if not intent_id or not quote_id:
            continue
        accepted.append(dict(row))
    return tuple(sorted(accepted, key=lambda item: (str(item["intent_id"]), str(item["quote_id"]))))


def price_rfq_fill_path(
    *,
    offered_output_atomic: int,
    direct_route_output_atomic: int,
    execution_cost_atomic: int,
) -> dict[str, int]:
    offered = integer(offered_output_atomic, "offered_output_atomic", minimum=0)
    direct = integer(direct_route_output_atomic, "direct_route_output_atomic", minimum=0)
    cost = integer(execution_cost_atomic, "execution_cost_atomic", minimum=0)
    return {
        "offered_output_atomic": offered,
        "direct_route_output_atomic": direct,
        "execution_cost_atomic": cost,
        "rfq_advantage_atomic": offered - direct - cost,
    }


def build_limit_order_fill_plan(
    quote: Mapping[str, Any],
    economics: Mapping[str, int],
    *,
    envelope: EvidenceEnvelope,
) -> dict[str, Any]:
    if envelope.blockers:
        raise ValueError("intent plan requires verified evidence")
    if quote.get("opt_in") is not True:
        raise ValueError("intent fill requires opt-in")
    payload = {
        "intent_id": str(quote["intent_id"]),
        "quote_id": str(quote["quote_id"]),
        "expires_at_ns": integer(quote["expires_at_ns"], "expires_at_ns", minimum=1),
        "economics": dict(economics),
        "state_generation": envelope.state_generation,
        "execution_authority": False,
    }
    return payload | {"plan_sha256": stable_hash("mega8-03/intent-plan/v1", payload)}


def qualify_opt_in_intent_fill(
    plan: Mapping[str, Any],
    *,
    envelope: EvidenceEnvelope,
    now_ns: int,
) -> OfflineDecision:
    reasons: list[str] = []
    if integer(plan.get("expires_at_ns"), "expires_at_ns", minimum=1) <= integer(now_ns, "now_ns", minimum=0):
        reasons.append("INTENT_EXPIRED")
    economics = plan.get("economics", {})
    if integer(economics.get("rfq_advantage_atomic"), "rfq_advantage_atomic") <= 0:
        reasons.append("RFQ_NOT_ECONOMICALLY_DOMINANT")
    return decision("PR-188", envelope=envelope, payload=dict(plan), reasons=reasons)


__all__ = [
    "build_limit_order_fill_plan",
    "ingest_solana_intent_quotes",
    "price_rfq_fill_path",
    "qualify_opt_in_intent_fill",
]
