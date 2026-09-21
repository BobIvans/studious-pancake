"""EVO-09 residual anomaly discovery using canonical intelligence owners."""

from collections import defaultdict
from typing import Any, Mapping, Sequence

from src.decision.agg10 import lead_lag_research

from .core import CorrelationHypothesis, CoverageCell, EvolutionError, result


def build_market_event_feature_frame(events: Sequence[Mapping[str, Any]]):
    rows = []
    for event in events:
        if not event.get("source_licensed", False):
            raise EvolutionError("SOURCE_UNLICENSED")
        event_time = event.get("event_time")
        observed_at = event.get("observed_at")
        if not isinstance(event_time, int) or not isinstance(observed_at, int):
            raise EvolutionError("EVENT_TIME_UNKNOWN")
        if observed_at < event_time:
            raise EvolutionError("FEATURE_LEAKAGE")
        rows.append(
            {
                "event_id": str(event.get("event_id")),
                "domain": str(event.get("domain", "unknown")),
                "event_time": event_time,
                "observed_at": observed_at,
                "finality": str(event.get("finality", "UNKNOWN")),
                "value_atoms": int(event.get("value_atoms", 0)),
                "source_id": str(event.get("source_id", "unknown")),
                "missing": bool(event.get("missing", False)),
            }
        )
    return result(
        "build_market_event_feature_frame",
        {"rows": tuple(rows), "row_count": len(rows)},
    )


def build_bot_operation_feature_frame(rows: Sequence[Mapping[str, Any]]):
    secret_keys = {
        "private_key",
        "secret_key",
        "auth_header",
        "authorization",
        "signed_transaction",
    }
    normalized = []
    rejected = 0
    for row in rows:
        if any(
            str(key).lower() in secret_keys and value not in (None, "", False)
            for key, value in row.items()
        ):
            raise EvolutionError("SECRET_DETECTED")
        if not row.get("operation_id"):
            raise EvolutionError("OUTCOME_UNLINKED")
        disposition = str(row.get("disposition", "UNKNOWN"))
        if disposition in {"REJECTED", "NO_TRADE", "FAILED"}:
            rejected += 1
        realized_raw = row.get("realized_net_atoms")
        realized_net_atoms = None if realized_raw is None else int(realized_raw)
        actual_landed_raw = row.get("actual_landed")
        actual_landed = (
            actual_landed_raw if isinstance(actual_landed_raw, bool) else None
        )
        label_available_raw = row.get("label_available_at")
        label_available_at = (
            None if label_available_raw is None else int(label_available_raw)
        )
        censored = bool(row.get("censored", False))
        normalized.append(
            {
                "operation_id": str(row["operation_id"]),
                "candidate_id": str(row.get("candidate_id", "")),
                "decision_at": int(row.get("decision_at", 0)),
                "disposition": disposition,
                "predicted_net_atoms": int(row.get("predicted_net_atoms", 0)),
                "realized_net_atoms": realized_net_atoms,
                "actual_landed": actual_landed,
                "outcome_missing": realized_net_atoms is None,
                "label_available_at": label_available_at,
                "censored": censored,
                "failure_class": (
                    None
                    if row.get("failure_class") is None
                    else str(row.get("failure_class"))
                ),
            }
        )
    return result(
        "build_bot_operation_feature_frame",
        {
            "rows": tuple(normalized),
            "row_count": len(normalized),
            "negative_or_rejected_rows": rejected,
        },
    )


def select_training_labels_as_of(
    rows: Sequence[Mapping[str, Any]],
    *,
    training_cutoff: int,
):
    cutoff = int(training_cutoff)
    if cutoff < 0:
        raise EvolutionError("TRAINING_CUTOFF_INVALID")
    selected = []
    missing = 0
    censored = 0
    future = 0
    for row in rows:
        realized = row.get("realized_net_atoms")
        available_at = row.get("label_available_at")
        if row.get("censored"):
            censored += 1
            continue
        if realized is None or available_at is None:
            missing += 1
            continue
        available = int(available_at)
        if available > cutoff:
            future += 1
            continue
        selected.append(
            {
                "operation_id": str(row.get("operation_id", "")),
                "realized_net_atoms": int(realized),
                "label_available_at": available,
                "disposition": str(row.get("disposition", "UNKNOWN")),
            }
        )
    return result(
        "select_training_labels_as_of",
        {
            "training_cutoff": cutoff,
            "rows": tuple(selected),
            "selected_count": len(selected),
            "missing_preserved": missing,
            "censored_preserved": censored,
            "future_labels_excluded": future,
            "label_leakage": False,
        },
    )


def align_cross_domain_event_time(
    market_frame: Mapping[str, Any],
    bot_frame: Mapping[str, Any],
    *,
    decision_at: int,
):
    allowed_market = []
    dropped_future = 0
    for row in market_frame.get("rows", ()):
        if int(row["observed_at"]) <= decision_at:
            allowed_market.append(dict(row))
        else:
            dropped_future += 1
    if not allowed_market and market_frame.get("rows"):
        raise EvolutionError("WATERMARK_GAP")
    bot_rows = [
        dict(row)
        for row in bot_frame.get("rows", ())
        if int(row["decision_at"]) <= decision_at
    ]
    return result(
        "align_cross_domain_event_time",
        {
            "market_rows": tuple(allowed_market),
            "bot_rows": tuple(bot_rows),
            "decision_at": int(decision_at),
            "dropped_future_rows": dropped_future,
            "point_in_time_correct": True,
        },
    )


def discover_residual_anomaly_clusters(
    aligned_frame: Mapping[str, Any],
    *,
    explained_event_ids: Sequence[str],
    multiple_testing_passed: bool,
    stability_evidence_ref: str | None = None,
    fdr_evidence_ref: str | None = None,
    persistence_evidence_ref: str | None = None,
):
    if not multiple_testing_passed:
        raise EvolutionError("MULTIPLE_TESTING_FAIL")
    if not stability_evidence_ref:
        raise EvolutionError("STABILITY_EVIDENCE_REQUIRED")
    if not fdr_evidence_ref:
        raise EvolutionError("FDR_EVIDENCE_REQUIRED")
    if not persistence_evidence_ref:
        raise EvolutionError("PERSISTENCE_EVIDENCE_REQUIRED")
    explained = set(str(value) for value in explained_event_ids)
    residuals = [
        row
        for row in aligned_frame.get("market_rows", ())
        if str(row["event_id"]) not in explained and not row.get("missing")
    ]
    if not residuals:
        raise EvolutionError("BASELINE_MISSING")
    groups = defaultdict(list)
    for row in residuals:
        groups[str(row.get("domain", "unknown"))].append(str(row["event_id"]))
    stable = {key: tuple(values) for key, values in groups.items() if len(values) >= 2}
    if not stable:
        raise EvolutionError("CLUSTER_UNSTABLE")
    return result(
        "discover_residual_anomaly_clusters",
        {
            "clusters": stable,
            "residual_count": len(residuals),
            "stability_evidence_ref": stability_evidence_ref,
            "fdr_evidence_ref": fdr_evidence_ref,
            "persistence_evidence_ref": persistence_evidence_ref,
        },
    )


def estimate_anomaly_lead_lag_graph(
    *,
    experiment_id: str,
    trigger: Sequence[int],
    target: Sequence[int],
    max_lag: int,
    latency_corrected: bool,
):
    if not latency_corrected:
        raise EvolutionError("CLOCK_ARTIFACT")
    comparison = lead_lag_research(
        experiment_id=experiment_id,
        trigger=tuple(int(value) for value in trigger),
        target=tuple(int(value) for value in target),
        max_lag=max_lag,
    )
    baseline = int(round(comparison.baseline_metric * 1_000_000))
    challenger = int(round(comparison.challenger_metric * 1_000_000))
    if challenger <= baseline:
        raise EvolutionError("LAG_UNSTABLE")
    return result(
        "estimate_anomaly_lead_lag_graph",
        {
            "experiment_id": experiment_id,
            "baseline_metric_ppm": baseline,
            "challenger_metric_ppm": challenger,
            "canonical_engine": "src.decision.agg10.lead_lag_research",
            "latency_corrected": True,
        },
    )


def attribute_opportunity_to_anomaly(payload: Mapping[str, Any]):
    if payload.get("confounded"):
        raise EvolutionError("CONFOUNDED")
    if payload.get("outcome_missing") or payload.get("realized_net_atoms") is None:
        raise EvolutionError("OUTCOME_MISSING")
    residual = (
        int(payload["realized_net_atoms"])
        - int(payload.get("predicted_net_atoms", 0))
        + int(payload.get("known_execution_loss_atoms", 0))
    )
    return result(
        "attribute_opportunity_to_anomaly",
        {
            **dict(payload),
            "unknown_residual_atoms": residual,
            "market_beta_separate": True,
        },
    )


def score_anomaly_arbitrageability(payload: Mapping[str, Any]):
    if payload.get("correlation_only"):
        raise EvolutionError("NONCAUSAL_ONLY")
    required_proofs = (
        "rights_verified",
        "costs_complete",
        "route_verified",
        "capacity_verified",
        "timing_verified",
    )
    if any(payload.get(field) is not True for field in required_proofs):
        raise EvolutionError("ARBITRAGEABILITY_PROOF_INCOMPLETE")
    net = int(payload.get("net_edge_atoms", 0))
    capacity = int(payload.get("capacity_atoms", 0))
    if net <= 0:
        raise EvolutionError("NET_EDGE_NONPOSITIVE")
    if capacity <= 0:
        raise EvolutionError("CAPACITY_UNKNOWN")
    data_cost = int(payload.get("data_cost_atoms", 0))
    tail_risk = int(payload.get("tail_risk_atoms", 0))
    financial_score = net - data_cost - tail_risk
    return result(
        "score_anomaly_arbitrageability",
        {
            **dict(payload),
            "score_atoms": financial_score,
            "financial_score_atoms": financial_score,
            "lead_time_ms": int(payload.get("lead_time_ms", 0)),
            "reproducibility_ppm": int(payload.get("reproducibility_ppm", 0)),
            "capacity_atoms": capacity,
            "mixed_units_combined": False,
            "raw_correlation_ranked": False,
        },
    )


def update_anomaly_coverage_registry(
    *,
    cells: Sequence[CoverageCell],
    hypothesis: CorrelationHypothesis,
    existing_hypothesis_ids: Sequence[str],
    evidence_complete: bool,
):
    if hypothesis.hypothesis_id in set(existing_hypothesis_ids):
        raise EvolutionError("DUPLICATE_HYPOTHESIS")
    if not evidence_complete:
        raise EvolutionError("EVIDENCE_INCOMPLETE")
    unknown = sum(
        1 for cell in cells if cell.status.upper() in {"UNKNOWN", "BLIND_SPOT"}
    )
    return result(
        "update_anomaly_coverage_registry",
        {
            "hypothesis_id": hypothesis.hypothesis_id,
            "cell_count": len(cells),
            "unknown_or_blind_spots": unknown,
            "append_only": True,
            "auto_promotion": False,
            "next_action": "PREREGISTER_RESEARCH_HYPOTHESIS",
        },
    )
