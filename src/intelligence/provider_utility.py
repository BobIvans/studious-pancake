"""Provider utility from exact observed event/candidate cohorts."""

from collections import defaultdict
from .common import digest


def unique_candidate_contribution(rows: list[dict]) -> dict:
    candidates = defaultdict(set)
    for row in rows:
        for candidate_id in row.get("candidate_ids", []):
            candidates[candidate_id].add(row["source_id"])
    providers = sorted({r["source_id"] for r in rows})
    return {
        p: {
            "unique_candidate_ids": sorted(
                c for c, sources in candidates.items() if sources == {p}
            ),
            "shared_candidate_ids": sorted(
                c
                for c, sources in candidates.items()
                if p in sources and len(sources) > 1
            ),
        }
        for p in providers
    }


def provider_disagreement_metrics(rows: list[dict]) -> dict:
    return {
        "observed": sum(r.get("provider_disagreement") is not None for r in rows),
        "disagreements": sum(r.get("provider_disagreement") is True for r in rows),
        "unknown": sum(r.get("provider_disagreement") is None for r in rows),
    }


def utility_per_quota_unit(unique_candidates: int, quota_units: int | None) -> dict:
    if unique_candidates < 0 or quota_units is not None and quota_units < 0:
        raise ValueError("negative provider metric")
    return {
        "unique_candidates": unique_candidates,
        "quota_units": quota_units,
        "utility_ppm": (
            unique_candidates * 1_000_000 // quota_units if quota_units else None
        ),
        "status": "MEASURED" if quota_units else "NOT_OBSERVED",
    }


def provider_funnel(rows: list[dict]) -> dict:
    if len({r["event_id"] for r in rows}) != len(rows):
        raise ValueError("duplicate provider observation")
    contribution = unique_candidate_contribution(rows)
    report = {}
    for source in sorted(contribution):
        events = [r for r in rows if r["source_id"] == source]
        latencies = [
            r["latency_ms"] for r in events if type(r.get("latency_ms")) is int
        ]
        quotas = [r["quota_units"] for r in events if type(r.get("quota_units")) is int]
        report[source] = {
            "evidence_refs": [
                {
                    "event_id": r["event_id"],
                    "row_sha256": digest(r),
                    "source_refs": r.get("source_refs"),
                    "payload_sha256": r.get("payload_sha256"),
                }
                for r in events
            ],
            "observations": len(events),
            "candidate_ids": sorted(
                {c for r in events for c in r.get("candidate_ids", [])}
            ),
            "latency_mean_ms": sum(latencies) / len(latencies) if latencies else None,
            "latency_observed": len(latencies),
            "stale_count": (
                sum(r.get("stale") is True for r in events)
                if any("stale" in r for r in events)
                else None
            ),
            "error_count": (
                sum(r.get("error") is True for r in events)
                if any("error" in r for r in events)
                else None
            ),
            "contribution": contribution[source],
            "disagreement": provider_disagreement_metrics(events),
            "utility": utility_per_quota_unit(
                len(contribution[source]["unique_candidate_ids"]),
                sum(quotas) if len(quotas) == len(events) else None,
            ),
        }
    return report
