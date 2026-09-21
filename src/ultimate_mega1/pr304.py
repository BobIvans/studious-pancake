"""PR-304 / NF-902..905: controlled replay failure diagnostics."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .core import ContractResult, UltimateMegaError, record, require_id, require_positive, stable_hash

_FORBIDDEN_MUTATIONS = {"program_version", "program_id", "rights", "liquidity"}


def define_replay_intervention_matrix(
    witness: Mapping[str, Any],
    interventions: Mapping[str, Sequence[Any]],
) -> ContractResult:
    if not interventions:
        raise UltimateMegaError("INTERVENTION_SET_REQUIRED")
    rows: list[dict[str, Any]] = []
    for field, values in sorted(interventions.items()):
        if field in _FORBIDDEN_MUTATIONS:
            raise UltimateMegaError("INVALID_COUNTERFACTUAL")
        if not values:
            continue
        for value in values:
            rows.append({"field": field, "value": value})
    if not rows:
        raise UltimateMegaError("INTERVENTION_SET_REQUIRED")
    return record(
        "define_replay_intervention_matrix",
        {
            "witness_hash": stable_hash("diagnostic-witness", witness),
            "interventions": rows,
            "single_factor_only": True,
        },
    )


def run_paired_failure_replays(
    baseline: Mapping[str, Any],
    variants: Sequence[Mapping[str, Any]],
    *,
    immutable_seed: str,
) -> ContractResult:
    require_id(immutable_seed, "immutable_seed")
    baseline_fp = stable_hash("paired-replay", baseline)
    pairs = []
    for variant in variants:
        pairs.append(
            {
                "changed_fields": tuple(sorted(variant.get("changed_fields", ()))),
                "before_fingerprint": baseline_fp,
                "after_fingerprint": stable_hash("paired-replay", variant),
                "reproducible": variant.get("reproducible", True) is True,
            }
        )
    if any(not row["reproducible"] for row in pairs):
        raise UltimateMegaError("NONDETERMINISM")
    return record(
        "run_paired_failure_replays",
        {"immutable_seed": immutable_seed, "pairs": pairs},
    )


def reduce_failure_trigger_set(
    paired_results: Mapping[str, Any],
    *,
    budget: int,
) -> ContractResult:
    require_positive(budget, "budget")
    pairs = list(paired_results.get("pairs", ()))
    if len(pairs) > budget:
        raise UltimateMegaError("BUDGET_EXCEEDED")
    changed = [
        tuple(row.get("changed_fields", ()))
        for row in pairs
        if row.get("after_fingerprint") != row.get("before_fingerprint")
    ]
    flattened = tuple(sorted({field for row in changed for field in row}))
    if not flattened:
        return record(
            "reduce_failure_trigger_set",
            {"cause_set": (), "unresolved_causes": ("UNKNOWN",)},
            status="UNKNOWN",
            blockers=("MULTIPLE_UNIDENTIFIED_CAUSES",),
        )
    return record(
        "reduce_failure_trigger_set",
        {
            "cause_set": flattened,
            "multifactor": len(flattened) > 1,
            "unresolved_causes": (),
        },
    )


def export_candidate_repair_hypothesis(
    trigger_witness: Mapping[str, Any],
    *,
    owner_map: Mapping[str, str],
    expected_outcome: str = "NO_TRADE",
) -> ContractResult:
    causes = tuple(str(x) for x in trigger_witness.get("cause_set", ()))
    if not causes:
        raise UltimateMegaError("UNSUPPORTED_CAUSAL_CLAIM")
    owners = []
    for cause in causes:
        owner = owner_map.get(cause)
        if not owner:
            raise UltimateMegaError("OWNER_AMBIGUOUS")
        owners.append((cause, require_id(owner, "owner")))
    return record(
        "export_candidate_repair_hypothesis",
        {
            "owners": tuple(owners),
            "regression_vector_hash": stable_hash("repair-vector", trigger_witness),
            "expected_outcome": expected_outcome,
            "live_path_created": False,
        },
    )
