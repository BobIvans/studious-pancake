"""PR-356 campaign, benchmark, red-team, and replication orchestration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

from .pr356_contracts import (
    CampaignManifest,
    MarketEpisodeRecord,
    PR356ContractError,
    ResearchVerdict,
    canonical_hash,
)
from .pr356_state_machine import measure_reaction_gap


def freeze_campaign_hypothesis(payload: Mapping[str, Any]) -> CampaignManifest:
    return CampaignManifest(
        campaign_id=str(payload["campaign_id"]),
        base_sha=str(payload["base_sha"]),
        hypothesis_ids=tuple(str(x) for x in payload["hypothesis_ids"]),
        universe=tuple(str(x) for x in payload["universe"]),
        budget_vector={str(k): int(v) for k, v in dict(payload["budget_vector"]).items()},
        train_cutoff=int(payload["train_cutoff"]),
        holdout_start=int(payload["holdout_start"]),
        holdout_end=int(payload["holdout_end"]),
        embargo=int(payload.get("embargo", 0)),
        reject_conditions=tuple(str(x) for x in payload["reject_conditions"]),
    )


def freeze_campaign_holdout(manifest: CampaignManifest) -> Mapping[str, Any]:
    return {
        "campaign_id": manifest.campaign_id,
        "holdout_start": manifest.holdout_start,
        "holdout_end": manifest.holdout_end,
        "embargo": manifest.embargo,
        "locked": True,
        "manifest_hash": manifest.manifest_hash,
    }


def publish_campaign_manifest(manifest: CampaignManifest) -> Mapping[str, Any]:
    return {**asdict(manifest), "manifest_hash": manifest.manifest_hash, "immutable": True}


def group_independent_market_episodes(
    rows: Sequence[Mapping[str, Any]], *, minimum_gap: int
) -> tuple[Mapping[str, Any], ...]:
    if minimum_gap < 0:
        raise PR356ContractError("MINIMUM_GAP_NEGATIVE")
    ordered = sorted(rows, key=lambda row: int(row["trigger_available_at"]))
    accepted = []
    last = None
    for row in ordered:
        current = int(row["trigger_available_at"])
        if last is not None and current - last < minimum_gap:
            continue
        accepted.append(dict(row))
        last = current
    if not accepted:
        raise PR356ContractError("INDEPENDENT_EPISODE_SET_EMPTY")
    return tuple(accepted)


def record_episode_prediction(
    *, episode_id: str, prediction_atoms: int, written_at: int, label_available_at: int
) -> Mapping[str, Any]:
    if written_at >= label_available_at:
        raise PR356ContractError("PREDICTION_NOT_BEFORE_LABEL")
    return {
        "episode_id": episode_id,
        "prediction_atoms": int(prediction_atoms),
        "written_at": int(written_at),
        "label_available_at": int(label_available_at),
    }


def mature_episode_label(
    *,
    episode: MarketEpisodeRecord,
    as_of: int,
    outcome_provenance: str | None = None,
) -> Mapping[str, Any]:
    if episode.label_status != "MATURE":
        return {
            "episode_id": episode.episode_id,
            "label_status": episode.label_status,
            "mature": False,
            "value_imputed": False,
        }
    if episode.label_available_at is None or as_of < episode.label_available_at:
        return {
            "episode_id": episode.episode_id,
            "label_status": "MISSING",
            "mature": False,
            "value_imputed": False,
        }
    provenance = outcome_provenance or episode.outcome_provenance
    if not provenance:
        raise PR356ContractError("MATURE_LABEL_PROVENANCE_REQUIRED")
    return {
        "episode_id": episode.episode_id,
        "label_status": "MATURE",
        "mature": True,
        "outcome_provenance": provenance,
        "value_imputed": False,
    }


def preserve_censored_episode(episode: MarketEpisodeRecord) -> Mapping[str, Any]:
    return {
        "episode_id": episode.episode_id,
        "label_status": episode.label_status,
        "censored": episode.label_status == "CENSORED",
        "missing": episode.label_status == "MISSING",
        "negative_label_assumed": False,
    }


def build_naive_visible_state_baseline(*, visible_atoms: int) -> Mapping[str, int]:
    if visible_atoms < 0:
        raise PR356ContractError("VISIBLE_LIQUIDITY_NEGATIVE")
    return {"predicted_capacity_atoms": visible_atoms}


def build_protocol_reachable_state_model(*, visible_atoms: int, reallocatable_atoms: int) -> Mapping[str, int]:
    if visible_atoms < 0 or reallocatable_atoms < 0:
        raise PR356ContractError("REACHABLE_LIQUIDITY_NEGATIVE")
    return {"predicted_capacity_atoms": visible_atoms + reallocatable_atoms}


def compare_reachable_capacity_error(
    *, naive_capacity_atoms: int, reachable_capacity_atoms: int, exact_capacity_atoms: int
) -> Mapping[str, Any]:
    if min(naive_capacity_atoms, reachable_capacity_atoms, exact_capacity_atoms) < 0:
        raise PR356ContractError("CAPACITY_NEGATIVE")
    naive_error = abs(naive_capacity_atoms - exact_capacity_atoms)
    reachable_error = abs(reachable_capacity_atoms - exact_capacity_atoms)
    return {
        "naive_error_atoms": naive_error,
        "reachable_error_atoms": reachable_error,
        "error_reduction_atoms": naive_error - reachable_error,
        "reachable_improves": reachable_error < naive_error,
    }


def measure_false_opportunity_reduction(*, naive_false: int, reachable_false: int) -> Mapping[str, int]:
    if min(naive_false, reachable_false) < 0 or reachable_false > naive_false:
        raise PR356ContractError("FALSE_OPPORTUNITY_COUNTS_INVALID")
    return {"removed_false_opportunities": naive_false - reachable_false}


def measure_missed_opportunity_recovery(*, naive_missed: int, reachable_missed: int) -> Mapping[str, int]:
    if min(naive_missed, reachable_missed) < 0 or reachable_missed > naive_missed:
        raise PR356ContractError("MISSED_OPPORTUNITY_COUNTS_INVALID")
    return {"recovered_valid_opportunities": naive_missed - reachable_missed}


def publish_reachability_verdict(
    *,
    campaign_id: str,
    hypothesis_id: str,
    comparison: Mapping[str, Any],
    exact_evidence_available: bool,
) -> ResearchVerdict:
    if not exact_evidence_available:
        verdict = "BLOCKED_EXTERNAL"
    elif comparison.get("reachable_improves") is True:
        verdict = "SUPPORTED_RESEARCH_ONLY"
    else:
        verdict = "REJECTED_WITH_EVIDENCE"
    receipt = canonical_hash({"comparison": dict(comparison), "exact_evidence_available": exact_evidence_available})
    return ResearchVerdict(
        campaign_id=campaign_id,
        hypothesis_id=hypothesis_id,
        verdict=verdict,
        uncertainty_ppm=0 if exact_evidence_available else 1_000_000,
        blind_spots=() if exact_evidence_available else ("EXACT_FORK_OR_SIMULATION_NOT_MATERIALIZED",),
        receipt_hash=receipt,
    )


def measure_campaign_reaction_gap(*, actionable_at_ms: int, response_at_ms: int) -> Mapping[str, int]:
    """Consumer alias; canonical primitive is W2F-044 measure_reaction_gap."""
    return measure_reaction_gap(actionable_at_ms=actionable_at_ms, response_at_ms=response_at_ms)


def preregister_research_proposal(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    required = ("hypothesis_id", "reject_condition", "universe", "holdout_id")
    missing = tuple(name for name in required if not payload.get(name))
    if missing:
        raise PR356ContractError(f"PREREGISTRATION_FIELDS_MISSING:{','.join(missing)}")
    frozen = dict(payload)
    frozen["execution_right"] = False
    frozen["preregistered"] = True
    frozen["registration_hash"] = canonical_hash(frozen)
    return frozen


def evaluate_experiment_independently(
    *, registration_hash: str, evaluator_input_hash: str, metric_pass: bool
) -> Mapping[str, Any]:
    if not registration_hash or not evaluator_input_hash:
        raise PR356ContractError("INDEPENDENT_EVALUATION_HASH_REQUIRED")
    return {
        "registration_hash": registration_hash,
        "evaluator_input_hash": evaluator_input_hash,
        "metric_pass": bool(metric_pass),
        "hypothesis_rewrite_allowed": False,
    }


def write_research_verdict(
    *, campaign_id: str, hypothesis_id: str, evaluation: Mapping[str, Any], blocked_external: bool = False
) -> ResearchVerdict:
    verdict = (
        "BLOCKED_EXTERNAL"
        if blocked_external
        else ("SUPPORTED_RESEARCH_ONLY" if evaluation.get("metric_pass") else "REJECTED_WITH_EVIDENCE")
    )
    return ResearchVerdict(
        campaign_id=campaign_id,
        hypothesis_id=hypothesis_id,
        verdict=verdict,
        uncertainty_ppm=1_000_000 if blocked_external else 0,
        blind_spots=("EXTERNAL_EVIDENCE_MISSING",) if blocked_external else (),
        receipt_hash=canonical_hash(dict(evaluation)),
    )


def freeze_benchmark_task(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    task = {
        "benchmark_id": str(payload["benchmark_id"]),
        "target": str(payload["target"]),
        "metric": str(payload["metric"]),
        "failure_condition": str(payload["failure_condition"]),
        "holdout_id": str(payload["holdout_id"]),
        "budget": dict(payload.get("budget", {})),
        "execution_right": False,
    }
    task["benchmark_hash"] = canonical_hash(task)
    return task


def define_reality_gap_chain(payload: Mapping[str, int | None]) -> Mapping[str, Any]:
    tiers = ("source", "state", "math", "simulation", "paper", "finalized")
    values = {tier: payload.get(tier) for tier in tiers}
    return {"tiers": tiers, "values": values, "unknown_tiers": tuple(tier for tier, value in values.items() if value is None)}


def attribute_reality_gap(*, source_error: int, semantic_error: int, timing_error: int, unknown_error: int) -> Mapping[str, int]:
    values = {
        "source": abs(int(source_error)),
        "semantic": abs(int(semantic_error)),
        "timing": abs(int(timing_error)),
        "unknown": abs(int(unknown_error)),
    }
    return {**values, "total": sum(values.values())}


def seal_benchmark_corpus(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    sealed = dict(payload)
    sealed["sealed"] = True
    sealed["corpus_hash"] = canonical_hash(payload)
    return sealed


def measure_opportunity_recall(*, detected: int, reference: int) -> Mapping[str, int]:
    if reference <= 0 or detected < 0 or detected > reference:
        raise PR356ContractError("OPPORTUNITY_RECALL_COUNTS_INVALID")
    return {"opportunity_recall_ppm": detected * 1_000_000 // reference}


def measure_false_candidate_rate(*, false_candidates: int, candidates: int) -> Mapping[str, int]:
    if candidates <= 0 or false_candidates < 0 or false_candidates > candidates:
        raise PR356ContractError("FALSE_CANDIDATE_COUNTS_INVALID")
    return {"false_candidate_rate_ppm": false_candidates * 1_000_000 // candidates}


def record_researcher_degrees_of_freedom(payload: Mapping[str, Sequence[Any]]) -> Mapping[str, Any]:
    counts = {name: len(tuple(values)) for name, values in payload.items()}
    return {"counts": counts, "total_trials": sum(counts.values())}


def detect_holdout_reuse(holdout_access_log: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    selection_reads = [row for row in holdout_access_log if row.get("purpose") in {"MODEL_SELECTION", "PROMPT_SELECTION", "FEATURE_SELECTION"}]
    return {"holdout_reuse_count": len(selection_reads), "integrity_ok": not selection_reads}


def _attack(name: str, *, detected: bool, fail_closed: bool) -> Mapping[str, Any]:
    return {"attack": name, "detected": detected, "fail_closed": fail_closed, "passed": detected and fail_closed}


def inject_source_delay_attack(*, detector_abstained: bool) -> Mapping[str, Any]:
    return _attack("RT-CASE-01", detected=detector_abstained, fail_closed=detector_abstained)


def inject_schema_unit_attack(*, schema_rejected: bool) -> Mapping[str, Any]:
    return _attack("RT-CASE-02", detected=schema_rejected, fail_closed=schema_rejected)


def inject_revision_attack(*, future_revision_excluded: bool) -> Mapping[str, Any]:
    return _attack("RT-CASE-03", detected=future_revision_excluded, fail_closed=future_revision_excluded)


def inject_deployment_upgrade_attack(*, generation_invalidated: bool) -> Mapping[str, Any]:
    return _attack("RT-CASE-04", detected=generation_invalidated, fail_closed=generation_invalidated)


def inject_topology_rights_attack(*, evidence_invalidated: bool) -> Mapping[str, Any]:
    return _attack("RT-CASE-05", detected=evidence_invalidated, fail_closed=evidence_invalidated)


def inject_provider_disagreement_attack(*, quarantined: bool) -> Mapping[str, Any]:
    return _attack("RT-CASE-06", detected=quarantined, fail_closed=quarantined)


def inject_label_censoring_attack(*, unknown_preserved: bool) -> Mapping[str, Any]:
    return _attack("RT-CASE-07", detected=unknown_preserved, fail_closed=unknown_preserved)


def prepare_replication_bundle(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    required = ("code_hash", "config_hash", "dataset_hash", "environment_hash")
    missing = tuple(name for name in required if not payload.get(name))
    if missing:
        raise PR356ContractError(f"REPLICATION_COMPONENT_MISSING:{','.join(missing)}")
    bundle = {name: str(payload[name]) for name in required}
    bundle["bundle_hash"] = canonical_hash(bundle)
    return bundle


def compare_replication_artifacts(
    *, expected: Mapping[str, Any], observed: Mapping[str, Any]
) -> Mapping[str, Any]:
    keys = ("code_hash", "config_hash", "dataset_hash", "environment_hash")
    differences = tuple(key for key in keys if expected.get(key) != observed.get(key))
    return {"reproduced": not differences, "differences": differences}


def quarantine_nonreproducible_result(comparison: Mapping[str, Any]) -> Mapping[str, Any]:
    reproduced = comparison.get("reproduced") is True
    return {"quarantined": not reproduced, "promotion_allowed": False if not reproduced else False, "research_only": True}
