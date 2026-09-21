"""PR-190 / PERP-01 — normalized Solana perp basis research."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .common import EvidenceEnvelope, OfflineDecision, PPM, decision, integer, require_rows


def collect_perp_mark_index_funding(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    require_rows(rows, "perp_rows")
    out: list[dict[str, Any]] = []
    for row in rows:
        market_id = str(row.get("market_id", "")).strip()
        if not market_id:
            continue
        mark = integer(row.get("mark_price_atomic"), "mark_price_atomic", minimum=1)
        index = integer(row.get("index_price_atomic"), "index_price_atomic", minimum=1)
        out.append(
            {
                "market_id": market_id,
                "mark_price_atomic": mark,
                "index_price_atomic": index,
                "funding_rate_ppm": integer(row.get("funding_rate_ppm", 0), "funding_rate_ppm"),
                "open_interest_atomic": integer(row.get("open_interest_atomic", 0), "open_interest_atomic", minimum=0),
                "available_at_ns": integer(row.get("available_at_ns", 0), "available_at_ns", minimum=0),
            }
        )
    return tuple(sorted(out, key=lambda item: (item["available_at_ns"], item["market_id"])))


def normalize_perp_contract_specs(spec: Mapping[str, Any]) -> dict[str, int | str]:
    return {
        "market_id": str(spec["market_id"]),
        "base_lot_atomic": integer(spec["base_lot_atomic"], "base_lot_atomic", minimum=1),
        "quote_lot_atomic": integer(spec["quote_lot_atomic"], "quote_lot_atomic", minimum=1),
        "maintenance_margin_ppm": integer(spec["maintenance_margin_ppm"], "maintenance_margin_ppm", minimum=0),
        "max_leverage_ppm": integer(spec["max_leverage_ppm"], "max_leverage_ppm", minimum=0),
    }


def detect_spot_perp_basis(
    *,
    spot_price_atomic: int,
    perp_mark_atomic: int,
) -> dict[str, int]:
    spot = integer(spot_price_atomic, "spot_price_atomic", minimum=1)
    mark = integer(perp_mark_atomic, "perp_mark_atomic", minimum=1)
    delta = mark - spot
    return {"basis_atomic": delta, "basis_ppm": delta * PPM // spot}


def rank_inventory_required_basis(
    candidates: Sequence[Mapping[str, Any]],
    *,
    envelope: EvidenceEnvelope,
) -> tuple[OfflineDecision, ...]:
    require_rows(candidates, "basis_candidates")
    ranked: list[OfflineDecision] = []
    for row in candidates:
        net = integer(row.get("conservative_net_atomic"), "conservative_net_atomic")
        margin = integer(row.get("required_margin_atomic"), "required_margin_atomic", minimum=1)
        payload = dict(row) | {"return_on_margin_ppm": net * PPM // margin}
        reasons = () if net > 0 else ("BASIS_NET_NOT_POSITIVE",)
        ranked.append(decision("PR-190", envelope=envelope, payload=payload, reasons=reasons, research_only=True))
    return tuple(sorted(ranked, key=lambda item: int(item.payload["return_on_margin_ppm"]), reverse=True))


__all__ = [
    "collect_perp_mark_index_funding",
    "detect_spot_perp_basis",
    "normalize_perp_contract_specs",
    "rank_inventory_required_basis",
]
