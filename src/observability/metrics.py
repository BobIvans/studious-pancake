from __future__ import annotations

import json
from collections import Counter, defaultdict
from statistics import median
from typing import TYPE_CHECKING, Any

from .store import ObservabilityStore

if TYPE_CHECKING:
    from .cross_plane_pr196 import CrossPlaneTruthStore


def _p95(vals: list[int]) -> int | str:
    if len(vals) < 2:
        return "N/A"
    vals = sorted(vals)
    return vals[int(0.95 * (len(vals) - 1))]


def _p50(vals: list[int]) -> float | str:
    return "N/A" if len(vals) < 2 else median(vals)


def verified_terminal_summary(
    truth_store: "CrossPlaneTruthStore | None",
) -> dict[str, object]:
    """Financial terminal metrics from PR-196 verified projection only."""

    if truth_store is None:
        return {
            "schema": "pr196.verified-terminal-metrics.v1",
            "source": "verified_terminal_projection",
            "raw_event_success_counted": False,
            "verified_successes": 0,
            "verified_failures": 0,
            "states": {},
            "realized_pnl_base_units_by_asset": {},
            "watermarks": {},
            "projection_checksum": None,
            "release_ready": False,
            "reason": "PR196_RECONCILED_PROJECTION_NOT_CONFIGURED",
        }
    return truth_store.metrics()


def rejection_funnel(store: ObservabilityStore) -> dict[str, Any]:
    """Operational event/rejection volume; never a financial success source."""

    counts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    lat: defaultdict[str, list[int]] = defaultdict(list)
    for row in store.db.execute(
        "SELECT event_type,reason_code,payload_json FROM event_log"
    ):
        counts[row["event_type"]] += 1
        if row["reason_code"]:
            reasons[row["reason_code"]] += 1
        attrs = json.loads(row["payload_json"]).get("attributes", {})
        if "latency_ms" in attrs and isinstance(attrs["latency_ms"], int):
            lat[row["event_type"]].append(attrs["latency_ms"])
    return {
        "stages": dict(counts),
        "reasons": dict(reasons),
        "latency": {
            "p50_ms": {key: _p50(values) for key, values in lat.items()},
            "p95_ms": {key: _p95(values) for key, values in lat.items()},
        },
        "ambiguous": reasons.get("AMBIGUOUS_SUBMISSION", 0),
        "not_attempted": counts.get("feasibility_rejected", 0)
        + counts.get("quote_rejected", 0),
    }


def daily_shadow_summary(
    store: ObservabilityStore,
    *,
    terminal_truth_store: "CrossPlaneTruthStore | None" = None,
) -> dict[str, Any]:
    funnel = rejection_funnel(store)
    result: dict[str, Any] = {
        "volume_events": sum(funnel["stages"].values()),
        "top_rejection_reasons": sorted(
            funnel["reasons"].items(), key=lambda item: (-item[1], item[0])
        )[:10],
        "funnel": funnel,
        "simulated_pnl_distribution": "N/A",
        "provider_health": "N/A",
        "quota": "N/A",
    }
    # Preserve the historical output exactly unless the authoritative projection
    # is explicitly wired by composition.
    if terminal_truth_store is not None:
        result["terminal_truth"] = verified_terminal_summary(terminal_truth_store)
    return result
