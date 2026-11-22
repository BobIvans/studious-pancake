"""Strategy/function performance diagnostics (OCA-W20).

Derived, read-only projection over the W10 runtime capture (canonical event
store), the W2 operation-episode projection, W13/W14 registries and the
repo-graph static layer. Produces the seven-section diagnostic result with
denominator-carrying metrics and evidence-tiered findings. Static graph edges
never imply execution; missing telemetry never reads as zero failures;
correlation never becomes causation without a controlled replay record.
"""

from __future__ import annotations

import json
import statistics
from typing import Any

SCHEMA = "studious.performance-diagnostics.v1"

STATUS_OBSERVED_ANOMALY = "OBSERVED_ANOMALY"
STATUS_ASSOCIATED_STAGE = "ASSOCIATED_STAGE"
STATUS_ROOT_CAUSE_HYPOTHESIS = "ROOT_CAUSE_HYPOTHESIS"
STATUS_CAUSALITY_SUPPORTED = "CAUSALITY_SUPPORTED_BY_CONTROLLED_TEST"
STATUS_CAUSALITY_PROVEN = "CAUSALITY_PROVEN"
STATUS_LOW_SAMPLE = "LOW_SAMPLE"
STATUS_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
STATUS_UNKNOWN = "UNKNOWN"

_MIN_SAMPLE = 5


def _quantiles(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "p50": round(ordered[len(ordered) // 2], 3),
        "p95": round(ordered[min(int(len(ordered) * 0.95), len(ordered) - 1)], 3),
        "p99": round(ordered[-1], 3),
    }


def _stage_health(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-stage metrics with explicit denominators."""
    stages: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        stages.setdefault(event.get("stage") or "UNKNOWN", []).append(event)
    health: dict[str, Any] = {}
    for stage in sorted(stages):
        stage_events = stages[stage]
        outcomes = [str(event.get("outcome")) for event in stage_events]
        errors = sum(
            1
            for o in outcomes
            if o in {"failed", "rejected", "Outcome.failed", "Outcome.rejected"}
        )
        retries = sum(1 for event in stage_events if event.get("retry_of") is not None)
        latencies = [
            event["stage_latency_ms"] / 1000.0
            for event in stage_events
            if event.get("stage_latency_ms") is not None
        ]
        health[stage] = {
            "invocations_denominator": len(stage_events),
            "completed": len(stage_events) - errors - retries,
            "errors": errors,
            "retries": retries,
            "error_rate": round(errors / len(stage_events), 4),
            "latency_quantiles_s": _quantiles(latencies),
            "latency_sample_size": len(latencies),
            "telemetry_status": "OBSERVED" if stage_events else "UNKNOWN",
        }
    return health


def build_diagnostics(
    *,
    store: Any,
    repo_sha: str,
    config_checksum: str,
    strategy_ref: str,
    static_callers: list[str] | None = None,
    baseline_cohort: dict[str, Any] | None = None,
    controlled_replay: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Seven-section diagnostic result for one strategy/route cohort.

    ``store`` is the canonical event store (W10 capture). ``static_callers``
    come from the repo graph and are reported as STATIC_ONLY context, never as
    runtime invocations. ``controlled_replay`` (fault-injection/replay record)
    is required before any causality tier above HYPOTHESIS is emitted.
    """
    static_callers = static_callers or []
    rows = list(store.db.execute("SELECT * FROM event_log ORDER BY sequence_no"))
    events = []
    for row in rows:
        record = {key: row[key] for key in row.keys()}
        record["outcome"] = str(record.get("outcome"))
        # P2-1: strategy attribution comes from captured payload attributes
        # (written by capture_stage), never guessed from names.
        try:
            payload = json.loads(record.get("payload_json") or "{}")
            record["strategy_ref"] = payload.get("attributes", {}).get("strategy_ref")
        except (ValueError, TypeError):
            record["strategy_ref"] = None
        events.append(record)
    if not events:
        return {
            "schema": SCHEMA,
            "status": STATUS_UNKNOWN,
            "unknowns": [
                "NO_RUNTIME_TELEMETRY: missing telemetry is UNKNOWN, never zero failures"
            ],
            "strategy_ref": strategy_ref,
            "repo_sha": repo_sha,
        }

    health = _stage_health(events)
    # Cohort definition and compatibility (W20 §2.3).
    first_payload: dict = {}
    try:
        first_payload = (
            json.loads(events[0].get("payload_json") or "{}") if events else {}
        )
    except (ValueError, TypeError):
        first_payload = {}
    cohort_route = first_payload.get("attributes", {}).get("route") or "UNKNOWN"
    attributed: dict[str, int] = {}
    for event in events:
        key = event["strategy_ref"] or "UNATTRIBUTED"
        attributed[key] = attributed.get(key, 0) + 1
    if strategy_ref != "unspecified":
        attributed_count = attributed.get(strategy_ref, 0)
        attribution_status = (
            "ATTRIBUTED" if attributed_count else "INSUFFICIENT_EVIDENCE"
        )
    else:
        attribution_status = "UNFILTERED"
        attributed_count = len(events)
    cohort = {
        "repo_sha": repo_sha,
        "config_checksum": config_checksum,
        "route": cohort_route,
        "compatibility": "COMPATIBLE_BASELINE (same repo SHA + config generation)",
        "sample_size": len(events),
        "low_sample": len(events) < _MIN_SAMPLE,
        "attribution_by_strategy_ref": dict(sorted(attributed.items())),
        "requested_strategy_ref": strategy_ref,
        "attribution_status": attribution_status,
        "attribution_note": (
            "events without a captured strategy_ref stay UNATTRIBUTED and are "
            "never silently assigned to the requested cohort"
        ),
    }
    if strategy_ref != "unspecified" and attributed_count == 0:
        return {
            "schema": SCHEMA,
            "status": STATUS_INSUFFICIENT_EVIDENCE,
            "strategy_ref": strategy_ref,
            "repo_sha": repo_sha,
            "cohort": cohort,
            "unknowns": [
                "no events attributed to the requested strategy_ref; "
                "attribution must come from capture_stage(strategy_ref=...)"
            ],
        }
    if strategy_ref != "unspecified" and attributed_count > 0:
        # P2-1: the requested cohort's metrics cover only its attributed
        # events; UNATTRIBUTED events are never silently mixed in.
        events = [e for e in events if e["strategy_ref"] == strategy_ref]
    cohort_route = first_payload.get("attributes", {}).get("route") or "UNKNOWN"
    total_invocations = len(events)
    total_errors = sum(entry["errors"] for entry in health.values())
    unknown_stages = sorted(
        stage
        for stage, entry in health.items()
        if entry["telemetry_status"] != "OBSERVED"
    )

    # Findings: evidence-tiered. A measured stage-error concentration in a
    # sufficient sample is an OBSERVED_ANOMALY; upstream/downstream stages are
    # ASSOCIATED_STAGE (correlation), never cause. Causality requires the
    # controlled replay record and a located injected callsite.
    findings: list[dict[str, Any]] = []
    for stage, entry in health.items():
        if entry["invocations_denominator"] < _MIN_SAMPLE:
            findings.append(
                {
                    "status": STATUS_LOW_SAMPLE,
                    "stage": stage,
                    "denominator": entry["invocations_denominator"],
                    "note": "insufficient sample for health ranking; no bad-function claims",
                }
            )
        elif entry["errors"] > 0 and entry["error_rate"] >= 0.5:
            findings.append(
                {
                    "status": STATUS_OBSERVED_ANOMALY,
                    "stage": stage,
                    "error_rate": entry["error_rate"],
                    "denominator": entry["invocations_denominator"],
                    "alternative_explanations": [
                        "upstream provider latency",
                        "queue/backpressure",
                        "data freshness/contract errors",
                    ],
                }
            )
    if (
        controlled_replay
        and controlled_replay.get("reproduced")
        and controlled_replay.get("located_stage")
    ):
        tier = (
            STATUS_CAUSALITY_PROVEN
            if controlled_replay.get("methodology_recorded")
            else STATUS_CAUSALITY_SUPPORTED
        )
        findings.append(
            {
                "status": tier,
                "stage": controlled_replay["located_stage"],
                "evidence": "controlled fault injection reproduced and localized",
            }
        )
    elif any(f["status"] == STATUS_OBSERVED_ANOMALY for f in findings):
        findings.append(
            {
                "status": STATUS_ASSOCIATED_STAGE,
                "note": "no controlled replay record: association only, no causality claims",
            }
        )

    return {
        "schema": SCHEMA,
        "strategy_ref": strategy_ref,
        "repo_sha": repo_sha,
        "config_generation": config_checksum,
        "sections": {
            "pipeline_health": {
                "total_invocations_denominator": total_invocations,
                "total_errors": total_errors,
                "capture_loss_events": sum(
                    1
                    for event in events
                    if event.get("event_type") == "observability_degraded"
                ),
                "unknown_stages": unknown_stages,
            },
            "function_callsite_health": health,
            "provider_data_health": {
                "status": STATUS_UNKNOWN,
                "reason": "provider-side telemetry not wired in this vertical (OCA-W13 observed-evidence gate)",
            },
            "strategy_outcome": {
                "status": STATUS_UNKNOWN,
                "reason": "no authoritative reconciliation evidence in this cohort; economic values stay UNKNOWN",
            },
            "anomaly_candidates": findings,
            "dependency_trace": {
                "static_callers": static_callers,
                "labelling": "STATIC_ONLY — these are graph facts, not runtime invocations",
            },
            "unknowns_and_next_evidence": [
                "provider telemetry producers (OCA-W13/W10 follow-up)",
                "authoritative reconciliation events for economic outcomes",
                "W15 temporal joins for cross-generation cohorts",
            ],
        },
        "cohort": cohort,
    }
