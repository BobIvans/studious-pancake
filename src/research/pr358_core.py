"""Deterministic PR-358 experiment-fabric, relation-science and service primitives.

All functions are offline, sender-free and stdlib-only.  Existing repository
owners remain authoritative for raw/PIT truth, statistical graphs, PR-357
world-model/VOI, product ledgers, execution, capital and release.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
from math import isqrt
from typing import Any, Iterable, Mapping, Sequence

from src.research.pr358_contracts import (
    EFFECT_BOUNDARY,
    PR358ContractError,
    canonical_hash,
)

PPM = 1_000_000
_ALLOWED_RELATION_STATUS = {
    "OBSERVED_RELATION",
    "REPLICATED_PREDICTIVE",
    "ECONOMICALLY_RELEVANT",
    "EXECUTABLE_SHADOW",
    "REJECTED_WITH_EVIDENCE",
    "INCONCLUSIVE",
}


def _nonempty(value: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PR358ContractError(code)
    return value


def _nonnegative(value: int, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PR358ContractError(code)
    return value


@dataclass(frozen=True, slots=True)
class ExperimentNode:
    node_id: str
    node_kind: str
    symbol_version: str
    params_hash: str
    upstream_artifact_hashes: tuple[str, ...]
    data_snapshot_ids: tuple[str, ...]
    tool_versions: tuple[str, ...]
    environment_lock_hash: str
    seed: int
    time_cutoff: int
    license_generation: str
    entitlement_generation: str
    semantic_version: str
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value, code in (
            (self.node_id, "PR358_NODE_ID_REQUIRED"),
            (self.node_kind, "PR358_NODE_KIND_REQUIRED"),
            (self.symbol_version, "PR358_NODE_VERSION_REQUIRED"),
            (self.params_hash, "PR358_PARAMS_HASH_REQUIRED"),
            (self.environment_lock_hash, "PR358_ENV_HASH_REQUIRED"),
            (self.license_generation, "PR358_LICENSE_GENERATION_REQUIRED"),
            (self.entitlement_generation, "PR358_ENTITLEMENT_GENERATION_REQUIRED"),
            (self.semantic_version, "PR358_SEMANTIC_VERSION_REQUIRED"),
        ):
            _nonempty(value, code)
        _nonnegative(self.seed, "PR358_SEED_NEGATIVE")
        _nonnegative(self.time_cutoff, "PR358_CUTOFF_NEGATIVE")


@dataclass(frozen=True, slots=True)
class CacheEntry:
    content_key: str
    output_hash: str
    time_cutoff: int
    license_generation: str
    entitlement_generation: str
    source_revision: str
    deployment_generation: str
    semantic_version: str

    def __post_init__(self) -> None:
        for value, code in (
            (self.content_key, "PR358_CACHE_KEY_REQUIRED"),
            (self.output_hash, "PR358_CACHE_OUTPUT_REQUIRED"),
            (self.license_generation, "PR358_CACHE_LICENSE_REQUIRED"),
            (self.entitlement_generation, "PR358_CACHE_ENTITLEMENT_REQUIRED"),
            (self.source_revision, "PR358_CACHE_REVISION_REQUIRED"),
            (self.deployment_generation, "PR358_CACHE_DEPLOYMENT_REQUIRED"),
            (self.semantic_version, "PR358_CACHE_SEMANTIC_REQUIRED"),
        ):
            _nonempty(value, code)
        _nonnegative(self.time_cutoff, "PR358_CACHE_CUTOFF_NEGATIVE")


@dataclass(frozen=True, slots=True)
class ComputeResourceClass:
    resource_id: str
    kind: str
    max_cost_units: int
    remote: bool = False
    paid: bool = False

    def __post_init__(self) -> None:
        _nonempty(self.resource_id, "PR358_RESOURCE_ID_REQUIRED")
        _nonempty(self.kind, "PR358_RESOURCE_KIND_REQUIRED")
        _nonnegative(self.max_cost_units, "PR358_RESOURCE_COST_NEGATIVE")
        if self.paid:
            raise PR358ContractError("PR358_PAID_RESOURCE_FORBIDDEN")


@dataclass(frozen=True, slots=True)
class CorrelationObservation:
    frame_id: str
    entity_id: str
    instrument_id: str
    bucket_id: str
    feature_name: str
    value: int
    unit: str
    event_at: int
    published_at: int
    received_at: int
    available_at: int
    revision: str
    source_id: str
    source_generation: str
    synthetic: bool
    privacy_class: str
    distribution_allowed: bool
    entitlement_scope: str
    provenance_hash: str

    def __post_init__(self) -> None:
        for value, code in (
            (self.frame_id, "PR358_FRAME_ID_REQUIRED"),
            (self.entity_id, "PR358_ENTITY_ID_REQUIRED"),
            (self.instrument_id, "PR358_INSTRUMENT_ID_REQUIRED"),
            (self.bucket_id, "PR358_BUCKET_ID_REQUIRED"),
            (self.feature_name, "PR358_FEATURE_REQUIRED"),
            (self.unit, "PR358_UNIT_REQUIRED"),
            (self.revision, "PR358_REVISION_REQUIRED"),
            (self.source_id, "PR358_SOURCE_REQUIRED"),
            (self.source_generation, "PR358_SOURCE_GENERATION_REQUIRED"),
            (self.privacy_class, "PR358_PRIVACY_CLASS_REQUIRED"),
            (self.entitlement_scope, "PR358_ENTITLEMENT_REQUIRED"),
            (self.provenance_hash, "PR358_PROVENANCE_REQUIRED"),
        ):
            _nonempty(value, code)
        clocks = (self.event_at, self.published_at, self.received_at, self.available_at)
        if any(
            isinstance(value, bool) or not isinstance(value, int) for value in clocks
        ):
            raise PR358ContractError("PR358_CLOCK_INTEGER_REQUIRED")
        if min(clocks) < 0:
            raise PR358ContractError("PR358_CLOCK_NEGATIVE")
        if not (
            self.event_at <= self.published_at <= self.received_at <= self.available_at
        ):
            raise PR358ContractError("PR358_CLOCK_ORDER_INVALID")


@dataclass(frozen=True, slots=True)
class RelationCandidateState:
    relation_id: str
    source_variables: tuple[str, ...]
    target_variables: tuple[str, ...]
    relation_family: str
    lag: int
    market_scope: str
    regime_scope: str
    method_id: str
    discovery_cutoff: int
    status: str = "OBSERVED_RELATION"
    causal_claim: bool = False
    execution_right: bool = False

    def __post_init__(self) -> None:
        _nonempty(self.relation_id, "PR358_RELATION_ID_REQUIRED")
        if not self.source_variables or not self.target_variables:
            raise PR358ContractError("PR358_RELATION_VARIABLES_REQUIRED")
        _nonnegative(self.lag, "PR358_RELATION_LAG_NEGATIVE")
        _nonnegative(self.discovery_cutoff, "PR358_RELATION_CUTOFF_NEGATIVE")
        if self.status not in _ALLOWED_RELATION_STATUS:
            raise PR358ContractError("PR358_RELATION_STATUS_INVALID")
        if self.causal_claim:
            raise PR358ContractError("PR358_CAUSAL_CLAIM_FORBIDDEN")
        if self.execution_right:
            raise PR358ContractError("PR358_EXECUTION_RIGHT_FORBIDDEN")


@dataclass(frozen=True, slots=True)
class MarketScienceService:
    service_id: str
    service_family: str
    input_schema: str
    output_schema: str
    evidence_tier: str
    max_age: int
    access_scope: str
    distribution_rights: bool
    privacy_class: str
    query_budget: int
    redaction_policy: str
    price_model: str
    prohibited_use: tuple[str, ...]
    live_effect: bool = False
    execution_right: bool = False

    def __post_init__(self) -> None:
        for value, code in (
            (self.service_id, "PR358_SERVICE_ID_REQUIRED"),
            (self.service_family, "PR358_SERVICE_FAMILY_REQUIRED"),
            (self.input_schema, "PR358_SERVICE_INPUT_SCHEMA_REQUIRED"),
            (self.output_schema, "PR358_SERVICE_OUTPUT_SCHEMA_REQUIRED"),
            (self.evidence_tier, "PR358_SERVICE_EVIDENCE_REQUIRED"),
            (self.access_scope, "PR358_SERVICE_ACCESS_REQUIRED"),
            (self.privacy_class, "PR358_SERVICE_PRIVACY_REQUIRED"),
            (self.redaction_policy, "PR358_SERVICE_REDACTION_REQUIRED"),
            (self.price_model, "PR358_SERVICE_PRICE_MODEL_REQUIRED"),
        ):
            _nonempty(value, code)
        _nonnegative(self.max_age, "PR358_SERVICE_MAX_AGE_NEGATIVE")
        if self.query_budget <= 0:
            raise PR358ContractError("PR358_SERVICE_QUERY_BUDGET_INVALID")
        if self.live_effect or self.execution_right:
            raise PR358ContractError("PR358_SERVICE_EFFECT_FORBIDDEN")


def define_experiment_node(**kwargs: Any) -> ExperimentNode:
    return ExperimentNode(**kwargs)


def compute_node_content_key(node: ExperimentNode) -> str:
    return canonical_hash(
        {
            "node_kind": node.node_kind,
            "symbol_version": node.symbol_version,
            "params_hash": node.params_hash,
            "upstream_artifact_hashes": sorted(node.upstream_artifact_hashes),
            "data_snapshot_ids": sorted(node.data_snapshot_ids),
            "tool_versions": sorted(node.tool_versions),
            "environment_lock_hash": node.environment_lock_hash,
            "seed": node.seed,
            "time_cutoff": node.time_cutoff,
            "license_generation": node.license_generation,
            "entitlement_generation": node.entitlement_generation,
            "semantic_version": node.semantic_version,
        }
    )


def validate_dag_acyclicity(nodes: Sequence[ExperimentNode]) -> bool:
    by_id = {node.node_id: node for node in nodes}
    if len(by_id) != len(nodes):
        raise PR358ContractError("PR358_DUPLICATE_DAG_NODE")
    for node in nodes:
        missing = set(node.dependencies) - set(by_id)
        if missing:
            raise PR358ContractError("PR358_DAG_DEPENDENCY_MISSING")
    temporary: set[str] = set()
    permanent: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in permanent:
            return
        if node_id in temporary:
            raise PR358ContractError("PR358_DAG_CYCLE")
        temporary.add(node_id)
        for dependency in by_id[node_id].dependencies:
            visit(dependency)
        temporary.remove(node_id)
        permanent.add(node_id)

    for node_id in sorted(by_id):
        visit(node_id)
    return True


def define_experiment_dag(nodes: Sequence[ExperimentNode]) -> Mapping[str, Any]:
    validate_dag_acyclicity(nodes)
    return {
        "nodes": tuple(sorted((node.node_id for node in nodes))),
        "content_keys": {
            node.node_id: compute_node_content_key(node) for node in nodes
        },
        "dag_hash": canonical_hash(
            tuple(
                sorted(
                    (
                        node.node_id,
                        tuple(sorted(node.dependencies)),
                        compute_node_content_key(node),
                    )
                    for node in nodes
                )
            )
        ),
        "execution_right": False,
    }


def validate_cache_provenance(
    entry: CacheEntry,
    *,
    expected_content_key: str,
    time_cutoff: int,
    license_generation: str,
    entitlement_generation: str,
    source_revision: str,
    deployment_generation: str,
    semantic_version: str,
) -> bool:
    expected = (
        expected_content_key,
        time_cutoff,
        license_generation,
        entitlement_generation,
        source_revision,
        deployment_generation,
        semantic_version,
    )
    actual = (
        entry.content_key,
        entry.time_cutoff,
        entry.license_generation,
        entry.entitlement_generation,
        entry.source_revision,
        entry.deployment_generation,
        entry.semantic_version,
    )
    if actual != expected:
        raise PR358ContractError("PR358_CACHE_PROVENANCE_MISMATCH")
    return True


def classify_cache_reuse(entry: CacheEntry, **expected: Any) -> str:
    try:
        validate_cache_provenance(entry, **expected)
    except PR358ContractError:
        return "INVALIDATE"
    return "REUSE_EXACT"


def compute_incremental_invalidation(
    nodes: Sequence[ExperimentNode],
    changed_node_ids: Iterable[str],
) -> tuple[str, ...]:
    validate_dag_acyclicity(nodes)
    reverse: dict[str, set[str]] = {node.node_id: set() for node in nodes}
    for node in nodes:
        for dependency in node.dependencies:
            reverse[dependency].add(node.node_id)
    impacted = set(changed_node_ids)
    unknown = impacted - set(reverse)
    if unknown:
        raise PR358ContractError("PR358_INVALIDATION_NODE_UNKNOWN")
    frontier = list(impacted)
    while frontier:
        current = frontier.pop()
        for child in reverse[current]:
            if child not in impacted:
                impacted.add(child)
                frontier.append(child)
    return tuple(sorted(impacted))


def define_compute_resource_class(
    resource_id: str,
    kind: str,
    max_cost_units: int,
    *,
    remote: bool = False,
    paid: bool = False,
) -> ComputeResourceClass:
    return ComputeResourceClass(resource_id, kind, max_cost_units, remote, paid)


def bind_node_cost_ceiling(requested_cost_units: int, ceiling_units: int) -> int:
    _nonnegative(requested_cost_units, "PR358_REQUESTED_COST_NEGATIVE")
    _nonnegative(ceiling_units, "PR358_COST_CEILING_NEGATIVE")
    if requested_cost_units > ceiling_units:
        raise PR358ContractError("PR358_COST_CEILING_EXCEEDED")
    return requested_cost_units


def schedule_research_node(
    node: ExperimentNode,
    resource: ComputeResourceClass,
    *,
    requested_cost_units: int,
) -> Mapping[str, Any]:
    bind_node_cost_ceiling(requested_cost_units, resource.max_cost_units)
    return {
        "node_id": node.node_id,
        "resource_id": resource.resource_id,
        "requested_cost_units": requested_cost_units,
        "proposal_only": True,
        "remote_mutation": False,
        "paid_resource": False,
    }


def define_experiment_matrix(
    trial_ids: Sequence[str],
    control_ids: Sequence[str],
    holdout_ids: Sequence[str],
) -> Mapping[str, Any]:
    if not trial_ids or not control_ids or not holdout_ids:
        raise PR358ContractError("PR358_EXPERIMENT_MATRIX_RESERVE_REQUIRED")
    all_ids = tuple(trial_ids) + tuple(control_ids) + tuple(holdout_ids)
    if len(set(all_ids)) != len(all_ids):
        raise PR358ContractError("PR358_EXPERIMENT_MATRIX_OVERLAP")
    return {
        "trials": tuple(trial_ids),
        "controls": tuple(control_ids),
        "holdouts": tuple(holdout_ids),
        "degrees_of_freedom": len(trial_ids),
    }


def deduplicate_equivalent_trials(
    trials: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    seen: set[str] = set()
    output = []
    for trial in trials:
        key = canonical_hash(trial)
        if key not in seen:
            seen.add(key)
            output.append(dict(trial))
    return tuple(output)


def reserve_control_trials(
    trials: Sequence[str],
    controls: Sequence[str],
    holdouts: Sequence[str],
) -> Mapping[str, tuple[str, ...]]:
    matrix = define_experiment_matrix(trials, controls, holdouts)
    return {
        "adaptive": matrix["trials"],
        "controls": matrix["controls"],
        "holdouts": matrix["holdouts"],
    }


def record_trial_degrees_of_freedom(
    family_id: str,
    tested_trial_ids: Sequence[str],
) -> Mapping[str, Any]:
    _nonempty(family_id, "PR358_FAMILY_ID_REQUIRED")
    return {
        "family_id": family_id,
        "trial_count": len(tuple(tested_trial_ids)),
        "tested_trial_ids": tuple(tested_trial_ids),
    }


def define_correlation_observation(**kwargs: Any) -> CorrelationObservation:
    return CorrelationObservation(**kwargs)


def materialize_correlation_frame(
    observations: Sequence[CorrelationObservation],
    *,
    decision_time: int,
) -> tuple[CorrelationObservation, ...]:
    _nonnegative(decision_time, "PR358_DECISION_TIME_NEGATIVE")
    selected = []
    for row in observations:
        if row.available_at <= decision_time:
            selected.append(row)
    return tuple(
        sorted(
            selected,
            key=lambda row: (
                row.entity_id,
                row.bucket_id,
                row.feature_name,
                row.available_at,
                row.revision,
            ),
        )
    )


def align_cross_bucket_available_at(
    observations: Sequence[CorrelationObservation],
) -> int:
    if len({row.bucket_id for row in observations}) < 2:
        raise PR358ContractError("PR358_CROSS_BUCKET_JOIN_REQUIRES_MULTIPLE_BUCKETS")
    return max(row.available_at for row in observations)


def bind_entity_identity(observations: Sequence[CorrelationObservation]) -> str:
    entities = {row.entity_id for row in observations}
    instruments = {row.instrument_id for row in observations}
    if len(entities) != 1 or len(instruments) != 1:
        raise PR358ContractError("PR358_JOIN_IDENTITY_MISMATCH")
    return f"{next(iter(entities))}:{next(iter(instruments))}"


def bind_feature_semantics(
    observations: Sequence[CorrelationObservation],
) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        sorted({(row.bucket_id, row.feature_name, row.unit) for row in observations})
    )


def define_semantic_join(
    observations: Sequence[CorrelationObservation],
    *,
    decision_time: int,
) -> Mapping[str, Any]:
    frame = materialize_correlation_frame(observations, decision_time=decision_time)
    if len({row.bucket_id for row in frame}) < 2:
        raise PR358ContractError("PR358_JOIN_BUCKET_COVERAGE_INSUFFICIENT")
    identity = bind_entity_identity(frame)
    return {
        "identity": identity,
        "available_at": align_cross_bucket_available_at(frame),
        "semantics": bind_feature_semantics(frame),
        "rows": frame,
        "join_hash": canonical_hash(
            tuple((row.frame_id, row.revision, row.provenance_hash) for row in frame)
        ),
    }


def validate_join_time_domain(
    observations: Sequence[CorrelationObservation],
    *,
    decision_time: int,
) -> bool:
    if any(row.available_at > decision_time for row in observations):
        raise PR358ContractError("PR358_JOIN_LOOKAHEAD")
    return True


def validate_join_identity(observations: Sequence[CorrelationObservation]) -> bool:
    bind_entity_identity(observations)
    return True


def materialize_joined_research_view(
    observations: Sequence[CorrelationObservation],
    *,
    decision_time: int,
) -> Mapping[str, Any]:
    validate_join_time_domain(observations, decision_time=decision_time)
    return define_semantic_join(observations, decision_time=decision_time)


def define_incremental_view(
    view_id: str,
    rows: Sequence[CorrelationObservation],
    *,
    watermark: int,
) -> Mapping[str, Any]:
    _nonempty(view_id, "PR358_VIEW_ID_REQUIRED")
    _nonnegative(watermark, "PR358_WATERMARK_NEGATIVE")
    admitted = tuple(
        sorted(
            (row for row in rows if row.available_at <= watermark),
            key=lambda row: (row.frame_id, row.revision, canonical_hash(row)),
        )
    )
    retractions: tuple[tuple[str, str], ...] = ()
    return {
        "view_id": view_id,
        "watermark": watermark,
        "rows": admitted,
        "retractions": retractions,
        "view_hash": canonical_hash(
            {
                "rows": tuple(canonical_hash(row) for row in admitted),
                "retractions": retractions,
            }
        ),
    }


def update_incremental_view(
    view: Mapping[str, Any],
    new_rows: Sequence[CorrelationObservation],
) -> Mapping[str, Any]:
    watermark = int(view["watermark"])
    prior = tuple(view["rows"])
    tombstones = {tuple(item) for item in view.get("retractions", ())}
    admitted = tuple(
        row
        for row in new_rows
        if row.available_at <= watermark
        and (row.frame_id, row.revision) not in tombstones
    )
    combined = prior + admitted
    dedup = {(row.frame_id, row.revision): row for row in combined}
    rows = tuple(dedup[key] for key in sorted(dedup))
    result = dict(view)
    result["rows"] = rows
    result["retractions"] = tuple(sorted(tombstones))
    result["view_hash"] = canonical_hash(
        {
            "rows": tuple(canonical_hash(row) for row in rows),
            "retractions": result["retractions"],
        }
    )
    return result


def retract_reorg_revision(
    view: Mapping[str, Any],
    *,
    frame_id: str,
    revision: str,
) -> Mapping[str, Any]:
    retractions = tuple(view.get("retractions", ())) + ((frame_id, revision),)
    rows = tuple(
        row
        for row in view["rows"]
        if not (row.frame_id == frame_id and row.revision == revision)
    )
    result = dict(view)
    result["rows"] = rows
    result["retractions"] = retractions
    result["view_hash"] = canonical_hash(
        {
            "rows": tuple((row.frame_id, row.revision) for row in rows),
            "retractions": retractions,
        }
    )
    return result


def snapshot_incremental_view(view: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "view_id": view["view_id"],
        "watermark": view["watermark"],
        "row_ids": tuple((row.frame_id, row.revision) for row in view["rows"]),
        "retractions": tuple(view.get("retractions", ())),
        "snapshot_hash": canonical_hash(
            {
                "view_id": view["view_id"],
                "watermark": view["watermark"],
                "row_ids": tuple((row.frame_id, row.revision) for row in view["rows"]),
                "retractions": tuple(view.get("retractions", ())),
            }
        ),
    }


def measure_stream_batch_equivalence(
    stream_rows: Sequence[CorrelationObservation],
    batch_rows: Sequence[CorrelationObservation],
) -> bool:
    stream = tuple(sorted(canonical_hash(row) for row in stream_rows))
    batch = tuple(sorted(canonical_hash(row) for row in batch_rows))
    return stream == batch


def assemble_experiment_evidence(
    *,
    experiment_id: str,
    dag_hash: str,
    node_receipts: Sequence[Mapping[str, Any]],
    failed_nodes: Sequence[str],
    licenses: Sequence[str],
) -> Mapping[str, Any]:
    _nonempty(experiment_id, "PR358_EXPERIMENT_ID_REQUIRED")
    _nonempty(dag_hash, "PR358_DAG_HASH_REQUIRED")
    payload = {
        "experiment_id": experiment_id,
        "dag_hash": dag_hash,
        "node_receipts": tuple(node_receipts),
        "failed_nodes": tuple(failed_nodes),
        "licenses": tuple(sorted(licenses)),
        "execution_right": False,
    }
    return {**payload, "evidence_hash": canonical_hash(payload)}


def attach_license_provenance(
    evidence: Mapping[str, Any],
    *,
    license_id: str,
    entitlement: str,
    redistribution_allowed: bool,
) -> Mapping[str, Any]:
    _nonempty(license_id, "PR358_LICENSE_ID_REQUIRED")
    _nonempty(entitlement, "PR358_ENTITLEMENT_REQUIRED")
    result = dict(evidence)
    result["license"] = {
        "license_id": license_id,
        "entitlement": entitlement,
        "redistribution_allowed": redistribution_allowed,
    }
    result["evidence_hash"] = canonical_hash(
        {key: value for key, value in result.items() if key != "evidence_hash"}
    )
    return result


def verify_evidence_bundle_replay(
    evidence: Mapping[str, Any],
    *,
    expected_hash: str,
) -> bool:
    if evidence.get("evidence_hash") != expected_hash:
        raise PR358ContractError("PR358_EVIDENCE_HASH_MISMATCH")
    body = {key: value for key, value in evidence.items() if key != "evidence_hash"}
    if canonical_hash(body) != expected_hash:
        raise PR358ContractError("PR358_EVIDENCE_TAMPERED")
    return True


def register_technology_candidate(
    technology_id: str,
    *,
    baseline_id: str,
    evidence_tier: str,
    cost_ceiling: int,
) -> Mapping[str, Any]:
    _nonempty(technology_id, "PR358_TECH_ID_REQUIRED")
    _nonempty(baseline_id, "PR358_TECH_BASELINE_REQUIRED")
    _nonempty(evidence_tier, "PR358_TECH_EVIDENCE_TIER_REQUIRED")
    _nonnegative(cost_ceiling, "PR358_TECH_COST_NEGATIVE")
    return {
        "technology_id": technology_id,
        "baseline_id": baseline_id,
        "evidence_tier": evidence_tier,
        "cost_ceiling": cost_ceiling,
        "status": "WATCH_ONLY" if evidence_tier == "WATCH" else "RESEARCH_ONLY",
        "automatic_promotion": False,
    }


def classify_technology_evidence_tier(
    *,
    replicated: bool,
    beats_baseline: bool,
    rights_verified: bool,
) -> str:
    if not rights_verified:
        return "BLOCKED_EXTERNAL"
    if not replicated:
        return "WATCH_ONLY"
    if not beats_baseline:
        return "REJECTED_WITH_EVIDENCE"
    return "SUPPORTED_RESEARCH_ONLY"


def define_vertical_experiment(
    vertical_id: str,
    buckets: Sequence[str],
    baselines: Sequence[str],
    metrics: Sequence[str],
    holdout: str,
) -> Mapping[str, Any]:
    if len(set(buckets)) < 2 or not baselines or not metrics:
        raise PR358ContractError("PR358_VERTICAL_CONTRACT_INCOMPLETE")
    return {
        "vertical_id": vertical_id,
        "buckets": tuple(buckets),
        "baselines": tuple(baselines),
        "metrics": tuple(metrics),
        "holdout": holdout,
        "execution_right": False,
    }


def instantiate_vertical_dag(
    vertical: Mapping[str, Any],
    nodes: Sequence[ExperimentNode],
) -> Mapping[str, Any]:
    dag = define_experiment_dag(nodes)
    return {
        "vertical_id": vertical["vertical_id"],
        "dag": dag,
        "execution_right": False,
    }


def measure_compute_reuse_rate(*, reused_nodes: int, total_nodes: int) -> int:
    if total_nodes <= 0 or not 0 <= reused_nodes <= total_nodes:
        raise PR358ContractError("PR358_REUSE_COUNTS_INVALID")
    return reused_nodes * PPM // total_nodes


def measure_cost_to_closed_verdict(
    *, total_cost_units: int, closed_verdicts: int
) -> int:
    _nonnegative(total_cost_units, "PR358_TOTAL_COST_NEGATIVE")
    if closed_verdicts <= 0:
        raise PR358ContractError("PR358_CLOSED_VERDICT_COUNT_INVALID")
    return total_cost_units // closed_verdicts


def define_relation_candidate(**kwargs: Any) -> RelationCandidateState:
    return RelationCandidateState(**kwargs)


def align_episode_available_at(
    observations: Sequence[CorrelationObservation],
) -> int:
    if not observations:
        raise PR358ContractError("PR358_EPISODE_EMPTY")
    return max(row.available_at for row in observations)


def sample_normal_control_episode(values: Sequence[int]) -> tuple[int, ...]:
    if len(values) < 2:
        raise PR358ContractError("PR358_CONTROL_SAMPLE_TOO_SMALL")
    return tuple(values[::2])


def sample_negative_control_episode(values: Sequence[int]) -> tuple[int, ...]:
    if len(values) < 2:
        raise PR358ContractError("PR358_NEGATIVE_CONTROL_TOO_SMALL")
    return tuple(reversed(values))


def _ranks(values: Sequence[int]) -> tuple[Fraction, ...]:
    groups: dict[int, list[int]] = {}
    for index, value in enumerate(values):
        groups.setdefault(value, []).append(index)
    result = [Fraction(0) for _ in values]
    position = 1
    for value in sorted(groups):
        indices = groups[value]
        low = position
        high = position + len(indices) - 1
        rank = Fraction(low + high, 2)
        for index in indices:
            result[index] = rank
        position = high + 1
    return tuple(result)


def _fraction_correlation(left: Sequence[Fraction], right: Sequence[Fraction]) -> int:
    if len(left) != len(right) or len(left) < 3:
        raise PR358ContractError("PR358_RELATION_SAMPLE_TOO_SMALL")
    n = len(left)
    mean_left = sum(left, Fraction(0)) / n
    mean_right = sum(right, Fraction(0)) / n
    covariance = sum(
        (x - mean_left) * (y - mean_right) for x, y in zip(left, right, strict=True)
    )
    left_ss = sum((x - mean_left) ** 2 for x in left)
    right_ss = sum((y - mean_right) ** 2 for y in right)
    if left_ss == 0 or right_ss == 0:
        return 0
    squared_correlation = Fraction(covariance * covariance / (left_ss * right_ss))
    if squared_correlation <= 0:
        return 0
    scaled_squared = squared_correlation * PPM * PPM
    magnitude = isqrt(scaled_squared.numerator // scaled_squared.denominator)
    return min(PPM, magnitude) if covariance >= 0 else -min(PPM, magnitude)


def run_rank_correlation_baseline(
    source: Sequence[int],
    target: Sequence[int],
) -> Mapping[str, int]:
    score = _fraction_correlation(_ranks(source), _ranks(target))
    return {"spearman_ppm": score, "abs_effect_ppm": abs(score)}


def run_cointegration_baseline(
    source: Sequence[int],
    target: Sequence[int],
) -> Mapping[str, int]:
    if len(source) != len(target) or len(source) < 3:
        raise PR358ContractError("PR358_COINTEGRATION_SAMPLE_INVALID")
    spread = [target[i] - source[i] for i in range(len(source))]
    mean = sum(spread) // len(spread)
    mad = sum(abs(value - mean) for value in spread) // len(spread)
    scale = max(1, max(abs(value) for value in spread))
    stability_ppm = max(0, PPM - mad * PPM // scale)
    return {"spread_mad": mad, "stability_ppm": stability_ppm}


def run_granger_predictive_baseline(
    source: Sequence[int],
    target: Sequence[int],
    *,
    lag: int = 1,
) -> Mapping[str, int]:
    if lag <= 0 or len(source) != len(target) or len(source) <= lag + 2:
        raise PR358ContractError("PR358_GRANGER_INPUT_INVALID")
    left = source[:-lag]
    right = target[lag:]
    score = run_rank_correlation_baseline(left, right)["spearman_ppm"]
    return {"lag": lag, "predictive_ppm": score}


def run_transfer_entropy_challenger(
    source: Sequence[int],
    target: Sequence[int],
) -> Mapping[str, int]:
    baseline = run_granger_predictive_baseline(source, target, lag=1)
    transitions = 0
    aligned = 0
    for left_delta, right_delta in zip(
        (b - a for a, b in zip(source, source[1:])),
        (b - a for a, b in zip(target[1:], target[2:])),
    ):
        transitions += 1
        aligned += int((left_delta > 0) == (right_delta > 0))
    directional_ppm = aligned * PPM // max(1, transitions)
    return {
        "directional_information_ppm": directional_ppm,
        "baseline_predictive_ppm": baseline["predictive_ppm"],
    }


def run_hawkes_excitation_challenger(
    trigger_times: Sequence[int],
    target_times: Sequence[int],
    *,
    window: int,
) -> Mapping[str, int]:
    if window <= 0 or not trigger_times or not target_times:
        raise PR358ContractError("PR358_HAWKES_INPUT_INVALID")
    hits = 0
    for trigger in trigger_times:
        if any(0 < target - trigger <= window for target in target_times):
            hits += 1
    return {"excitation_ppm": hits * PPM // len(trigger_times), "window": window}


def compare_relation_methods(
    method_metrics: Mapping[str, int],
    *,
    baseline_method: str,
) -> Mapping[str, Any]:
    if baseline_method not in method_metrics:
        raise PR358ContractError("PR358_BASELINE_METHOD_MISSING")
    best_method, best_value = max(
        method_metrics.items(), key=lambda pair: (pair[1], pair[0])
    )
    return {
        "baseline_method": baseline_method,
        "best_method": best_method,
        "best_value": best_value,
        "incremental_gain": best_value - method_metrics[baseline_method],
    }


def detect_clock_artifact(
    source_available_at: Sequence[int],
    target_event_at: Sequence[int],
) -> bool:
    if len(source_available_at) != len(target_event_at):
        raise PR358ContractError("PR358_CLOCK_ARTIFACT_INPUT_MISMATCH")
    return any(
        source > target for source, target in zip(source_available_at, target_event_at)
    )


def detect_common_cause_candidate(
    source_effect_ppm: int,
    target_effect_ppm: int,
    conditioned_effect_ppm: int,
    *,
    collapse_threshold_ppm: int = 250_000,
) -> bool:
    raw = min(abs(source_effect_ppm), abs(target_effect_ppm))
    return raw > 0 and abs(conditioned_effect_ppm) * PPM // raw < collapse_threshold_ppm


def downgrade_confounded_relation(
    *,
    clock_artifact: bool,
    common_cause: bool,
    negative_control_triggered: bool,
) -> str:
    if clock_artifact or common_cause or negative_control_triggered:
        return "INCONCLUSIVE"
    return "REPLICATED_PREDICTIVE"


def measure_precursor_lead_time(
    trigger_times: Sequence[int],
    target_times: Sequence[int],
) -> Mapping[str, int]:
    leads = []
    for trigger in trigger_times:
        future = [target - trigger for target in target_times if target >= trigger]
        if future:
            leads.append(min(future))
    if not leads:
        return {"count": 0, "median_lead": 0}
    ordered = sorted(leads)
    return {"count": len(leads), "median_lead": ordered[len(ordered) // 2]}


def measure_sequence_precision_recall(
    predicted_events: Sequence[int],
    actual_events: Sequence[int],
    *,
    tolerance: int,
) -> Mapping[str, int]:
    if tolerance < 0:
        raise PR358ContractError("PR358_SEQUENCE_TOLERANCE_NEGATIVE")
    predicted = tuple(sorted(predicted_events))
    actual = tuple(sorted(actual_events))
    predicted_index = 0
    actual_index = 0
    matched = 0
    while predicted_index < len(predicted) and actual_index < len(actual):
        event = predicted[predicted_index]
        target = actual[actual_index]
        if abs(event - target) <= tolerance:
            matched += 1
            predicted_index += 1
            actual_index += 1
        elif event < target - tolerance:
            predicted_index += 1
        else:
            actual_index += 1
    precision = matched * PPM // max(1, len(predicted))
    recall = matched * PPM // max(1, len(actual))
    return {"precision_ppm": precision, "recall_ppm": recall}


def fit_tail_dependence_baseline(
    source: Sequence[int],
    target: Sequence[int],
    *,
    threshold: int,
) -> Mapping[str, int]:
    if len(source) != len(target) or not source:
        raise PR358ContractError("PR358_TAIL_INPUT_INVALID")
    source_tail = [index for index, value in enumerate(source) if value >= threshold]
    joint = sum(1 for index in source_tail if target[index] >= threshold)
    return {
        "source_tail_count": len(source_tail),
        "upper_tail_ppm": joint * PPM // max(1, len(source_tail)),
    }


def estimate_directional_information_flow(
    source: Sequence[int],
    target: Sequence[int],
) -> int:
    return int(
        run_transfer_entropy_challenger(source, target)["directional_information_ppm"]
    )


def bind_relation_units(units: Mapping[str, str]) -> Mapping[str, str]:
    if not units or any(not value for value in units.values()):
        raise PR358ContractError("PR358_RELATION_UNITS_REQUIRED")
    return dict(sorted(units.items()))


def reject_dimensionally_invalid_law(
    left_unit: str,
    right_unit: str,
    *,
    operator: str,
) -> bool:
    if operator in {"+", "-"} and left_unit != right_unit:
        return True
    return False


def test_accounting_invariant(
    inflows: Sequence[int],
    outflows: Sequence[int],
    *,
    tolerance: int = 0,
) -> Mapping[str, int | bool]:
    delta = sum(inflows) - sum(outflows)
    return {"delta": delta, "holds": abs(delta) <= tolerance}


def find_minimal_counterexample(
    expected: Sequence[int],
    observed: Sequence[int],
) -> Mapping[str, int] | None:
    if len(expected) != len(observed):
        raise PR358ContractError("PR358_COUNTEREXAMPLE_INPUT_MISMATCH")
    for index, (left, right) in enumerate(zip(expected, observed, strict=True)):
        if left != right:
            return {"index": index, "expected": left, "observed": right}
    return None


def measure_relation_half_life(effect_path: Sequence[int]) -> int | None:
    if not effect_path:
        return None
    initial = abs(effect_path[0])
    if initial == 0:
        return 0
    for index, value in enumerate(effect_path[1:], 1):
        if abs(value) * 2 <= initial:
            return index
    return None


def detect_relation_sign_flip(effect_path: Sequence[int]) -> bool:
    signs = {1 if value > 0 else -1 for value in effect_path if value != 0}
    return len(signs) > 1


def detect_relation_topology_break(
    prior_sources: Sequence[str],
    current_sources: Sequence[str],
) -> bool:
    return set(prior_sources) != set(current_sources)


def detect_relation_negative_transfer(
    *,
    target_local_loss: int,
    transferred_loss: int,
) -> bool:
    return transferred_loss > target_local_loss


def apply_relation_multiple_testing_control(
    p_values_ppm: Mapping[str, int],
    *,
    alpha_ppm: int,
) -> tuple[str, ...]:
    if not 0 < alpha_ppm <= PPM or not p_values_ppm:
        raise PR358ContractError("PR358_FDR_POLICY_INVALID")
    for value in p_values_ppm.values():
        if not 0 <= value <= PPM:
            raise PR358ContractError("PR358_P_VALUE_RANGE")
    ordered = sorted(p_values_ppm.items(), key=lambda pair: (pair[1], pair[0]))
    m = len(ordered)
    accepted_index = -1
    for index, (_, p_value) in enumerate(ordered, 1):
        if p_value * m <= alpha_ppm * index:
            accepted_index = index
    if accepted_index < 0:
        return ()
    cutoff = ordered[accepted_index - 1][1]
    return tuple(sorted(name for name, value in ordered if value <= cutoff))


def record_relation_trial_count(
    family_id: str,
    trial_ids: Sequence[str],
) -> Mapping[str, Any]:
    return record_trial_degrees_of_freedom(family_id, trial_ids)


def falsify_unstable_relation(
    *,
    heldout_effect_ppm: int,
    minimum_effect_ppm: int,
    sign_flip: bool,
    confounded: bool,
) -> str:
    if confounded or sign_flip or abs(heldout_effect_ppm) < minimum_effect_ppm:
        return "REJECTED_WITH_EVIDENCE"
    return "SUPPORTED_RESEARCH_ONLY"


def compile_relation_to_hypothesis_ir(
    relation: RelationCandidateState,
    *,
    evidence_hash: str,
) -> Mapping[str, Any]:
    return {
        "target_owner": "PR-357 hypothesis input",
        "relation_id": relation.relation_id,
        "evidence_hash": evidence_hash,
        "proposal_only": True,
        "execution_right": False,
    }


def compile_relation_to_world_model_prior(
    relation: RelationCandidateState,
    *,
    evidence_hash: str,
) -> Mapping[str, Any]:
    return {
        "target_owner": "src.research.pr357_core.BeliefState",
        "relation_id": relation.relation_id,
        "evidence_hash": evidence_hash,
        "prior_only": True,
        "execution_right": False,
    }


def compile_relation_to_bootstrap_prior(
    relation: RelationCandidateState,
    *,
    evidence_hash: str,
) -> Mapping[str, Any]:
    return {
        "target_owner": "PR-357 bootstrap prior retrieval",
        "relation_id": relation.relation_id,
        "evidence_hash": evidence_hash,
        "prior_only": True,
        "execution_right": False,
    }


def compile_relation_to_voi_question(
    relation: RelationCandidateState,
    *,
    evidence_hash: str,
) -> Mapping[str, Any]:
    return {
        "target_owner": "PR-357 decision-aware VOI",
        "relation_id": relation.relation_id,
        "evidence_hash": evidence_hash,
        "question_only": True,
        "execution_right": False,
    }


def materialize_relation_atlas_snapshot(
    relations: Sequence[RelationCandidateState],
    *,
    knowledge_cutoff: int,
) -> Mapping[str, Any]:
    _nonnegative(knowledge_cutoff, "PR358_ATLAS_CUTOFF_NEGATIVE")
    if any(relation.discovery_cutoff > knowledge_cutoff for relation in relations):
        raise PR358ContractError("PR358_ATLAS_LOOKAHEAD_RELATION")
    counts: dict[str, int] = {}
    for relation in relations:
        counts[relation.status] = counts.get(relation.status, 0) + 1
    body = {
        "knowledge_cutoff": knowledge_cutoff,
        "relation_ids": tuple(sorted(relation.relation_id for relation in relations)),
        "status_counts": dict(sorted(counts.items())),
        "execution_right": False,
    }
    return {**body, "snapshot_hash": canonical_hash(body)}


def define_market_science_service(
    *,
    service_id: str,
    service_family: str,
    input_schema: str,
    output_schema: str,
    evidence_tier: str,
    max_age: int,
    access_scope: str,
    distribution_rights: bool,
    privacy_class: str,
    query_budget: int,
    redaction_policy: str,
    price_model: str,
    prohibited_use: Sequence[str],
) -> MarketScienceService:
    return MarketScienceService(
        service_id=service_id,
        service_family=service_family,
        input_schema=input_schema,
        output_schema=output_schema,
        evidence_tier=evidence_tier,
        max_age=max_age,
        access_scope=access_scope,
        distribution_rights=distribution_rights,
        privacy_class=privacy_class,
        query_budget=query_budget,
        redaction_policy=redaction_policy,
        price_model=price_model,
        prohibited_use=tuple(prohibited_use),
    )


def bind_distribution_entitlement(
    service: MarketScienceService,
    *,
    requested_scope: str,
) -> bool:
    if not service.distribution_rights:
        raise PR358ContractError("PR358_DISTRIBUTION_RIGHTS_DENIED")
    if requested_scope != service.access_scope:
        raise PR358ContractError("PR358_ENTITLEMENT_SCOPE_DENIED")
    return True


def bind_product_query_budget(
    service: MarketScienceService,
    *,
    used_queries: int,
) -> int:
    _nonnegative(used_queries, "PR358_QUERY_USAGE_NEGATIVE")
    if used_queries >= service.query_budget:
        raise PR358ContractError("PR358_QUERY_BUDGET_EXHAUSTED")
    return service.query_budget - used_queries


def bind_product_redaction_policy(
    service: MarketScienceService,
    *,
    privacy_class: str,
) -> str:
    if privacy_class != service.privacy_class:
        raise PR358ContractError("PR358_PRIVACY_CLASS_MISMATCH")
    return service.redaction_policy


def bind_product_staleness(
    service: MarketScienceService,
    *,
    artifact_age: int,
) -> bool:
    _nonnegative(artifact_age, "PR358_ARTIFACT_AGE_NEGATIVE")
    if artifact_age > service.max_age:
        raise PR358ContractError("PR358_SERVICE_ARTIFACT_STALE")
    return False


def estimate_service_cost_floor(
    *,
    compute_cost: int,
    source_cost: int,
    verification_cost: int,
    support_cost: int,
) -> int:
    values = (compute_cost, source_cost, verification_cost, support_cost)
    if any(value < 0 for value in values):
        raise PR358ContractError("PR358_SERVICE_COST_NEGATIVE")
    return sum(values)


def compare_subscription_usage_pricing(
    *,
    subscription_revenue: int,
    usage_revenue: int,
    cost_floor: int,
) -> Mapping[str, Any]:
    return {
        "subscription_margin": subscription_revenue - cost_floor,
        "usage_margin": usage_revenue - cost_floor,
        "simulated_only": True,
        "customer_billing": False,
    }


def define_solver_market_episode(
    episode_id: str,
    intent_spec: Mapping[str, Any],
) -> Mapping[str, Any]:
    _nonempty(episode_id, "PR358_SOLVER_EPISODE_ID_REQUIRED")
    return {
        "episode_id": episode_id,
        "intent_spec": dict(intent_spec),
        "simulation_only": True,
        "execution_right": False,
    }


def normalize_external_intent(intent: Mapping[str, Any]) -> Mapping[str, Any]:
    allowed = {"input_asset", "output_asset", "amount", "min_output", "deadline"}
    if not allowed.issubset(intent):
        raise PR358ContractError("PR358_INTENT_FIELDS_MISSING")
    return {key: intent[key] for key in sorted(allowed)}


def simulate_solver_competition(
    quotes: Mapping[str, int],
    costs: Mapping[str, int],
) -> Mapping[str, Any]:
    if not quotes or set(quotes) != set(costs):
        raise PR358ContractError("PR358_SOLVER_COMPETITION_INPUT_INVALID")
    net = {solver: quotes[solver] - costs[solver] for solver in quotes}
    winner = max(net, key=lambda solver: (net[solver], solver))
    return {
        "winner": winner,
        "net_outputs": dict(sorted(net.items())),
        "simulation_only": True,
        "execution_right": False,
    }


def define_keeper_job_offer(
    *,
    job_id: str,
    authorization_ref: str,
    worst_debit: int,
    service_fee: int,
) -> Mapping[str, Any]:
    _nonnegative(worst_debit, "PR358_KEEPER_DEBIT_NEGATIVE")
    _nonnegative(service_fee, "PR358_KEEPER_FEE_NEGATIVE")
    return {
        "job_id": job_id,
        "authorization_ref": authorization_ref,
        "worst_debit": worst_debit,
        "service_fee": service_fee,
        "simulation_only": True,
        "execution_right": False,
    }


def simulate_keeper_job_market(
    offers: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    if not offers:
        raise PR358ContractError("PR358_KEEPER_OFFERS_EMPTY")
    best = min(
        offers, key=lambda offer: (int(offer["service_fee"]), str(offer["job_id"]))
    )
    return {
        "selected_job_id": best["job_id"],
        "simulation_only": True,
        "submission_access": False,
    }


def define_sponsorship_episode(
    *,
    provider: str,
    network_fee: int,
    abuse_loss: int,
) -> Mapping[str, Any]:
    _nonnegative(network_fee, "PR358_SPONSOR_NETWORK_FEE_NEGATIVE")
    _nonnegative(abuse_loss, "PR358_SPONSOR_ABUSE_LOSS_NEGATIVE")
    return {
        "provider": provider,
        "network_fee": network_fee,
        "abuse_loss": abuse_loss,
        "simulation_only": True,
        "paymaster_spending": False,
    }


def estimate_sponsor_reserve_requirement(
    *,
    network_fee: int,
    failure_cost: int,
    abuse_loss: int,
) -> int:
    values = (network_fee, failure_cost, abuse_loss)
    if any(value < 0 for value in values):
        raise PR358ContractError("PR358_SPONSOR_COST_NEGATIVE")
    return sum(values)


def define_machine_payment_quote(
    *,
    service_id: str,
    price_units: int,
    settlement_overhead: int,
) -> Mapping[str, Any]:
    _nonnegative(price_units, "PR358_PAYMENT_PRICE_NEGATIVE")
    _nonnegative(settlement_overhead, "PR358_PAYMENT_OVERHEAD_NEGATIVE")
    return {
        "service_id": service_id,
        "price_units": price_units,
        "settlement_overhead": settlement_overhead,
        "simulation_only": True,
        "payment_sent": False,
    }


def simulate_x402_single_payment(quote: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "service_id": quote["service_id"],
        "total_simulated_cost": int(quote["price_units"])
        + int(quote["settlement_overhead"]),
        "payment_state": "SIMULATED_ONLY",
        "payment_sent": False,
    }


def simulate_x402_batch_settlement(
    quotes: Sequence[Mapping[str, Any]],
    *,
    batch_overhead: int,
) -> Mapping[str, Any]:
    _nonnegative(batch_overhead, "PR358_BATCH_OVERHEAD_NEGATIVE")
    return {
        "call_count": len(quotes),
        "simulated_service_value": sum(int(quote["price_units"]) for quote in quotes),
        "settlement_overhead": batch_overhead,
        "payment_state": "SIMULATED_ONLY",
        "payment_sent": False,
    }


def compute_scoped_reputation_features(
    *,
    validated_successes: int,
    failures: int,
    distinct_referees: int,
) -> Mapping[str, int]:
    if min(validated_successes, failures, distinct_referees) < 0:
        raise PR358ContractError("PR358_REPUTATION_COUNT_NEGATIVE")
    total = validated_successes + failures
    return {
        "success_ppm": validated_successes * PPM // max(1, total),
        "referee_diversity": distinct_referees,
    }


def detect_sybil_or_feedback_risk(
    *,
    feedback_count: int,
    distinct_referees: int,
) -> bool:
    if feedback_count < 0 or distinct_referees < 0:
        raise PR358ContractError("PR358_FEEDBACK_COUNT_NEGATIVE")
    return feedback_count >= 3 and distinct_referees * 2 < feedback_count


def define_simulation_proof_offer(
    *,
    offer_id: str,
    candidate_hash: str,
    state_root: str,
    artifact_hash: str,
    replay_method: str,
    verification_cost: int,
) -> Mapping[str, Any]:
    _nonnegative(verification_cost, "PR358_VERIFICATION_COST_NEGATIVE")
    return {
        "offer_id": offer_id,
        "candidate_hash": candidate_hash,
        "state_root": state_root,
        "artifact_hash": artifact_hash,
        "replay_method": replay_method,
        "verification_cost": verification_cost,
        "proof_optional": True,
        "execution_right": False,
    }


def measure_information_leakage(
    *,
    revealed_fields: int,
    total_fields: int,
) -> int:
    if total_fields <= 0 or not 0 <= revealed_fields <= total_fields:
        raise PR358ContractError("PR358_LEAKAGE_COUNTS_INVALID")
    return revealed_fields * PPM // total_fields


def define_confidential_service_payload(
    *,
    service_id: str,
    fields: Sequence[str],
    reveal_fields: Sequence[str],
) -> Mapping[str, Any]:
    if not set(reveal_fields).issubset(set(fields)):
        raise PR358ContractError("PR358_REVEAL_POLICY_INVALID")
    return {
        "service_id": service_id,
        "field_count": len(fields),
        "reveal_fields": tuple(reveal_fields),
        "private_orderflow_ingested": False,
        "execution_right": False,
    }


def compose_multi_service_workflow(
    service_ids: Sequence[str],
) -> Mapping[str, Any]:
    if not service_ids or len(set(service_ids)) != len(service_ids):
        raise PR358ContractError("PR358_SERVICE_COMPOSITION_INVALID")
    return {
        "service_ids": tuple(service_ids),
        "composition_hash": canonical_hash(tuple(service_ids)),
        "external_service_activation": False,
    }


def measure_service_unit_economics(
    *,
    simulated_revenue: int,
    total_cost: int,
) -> Mapping[str, int | bool]:
    _nonnegative(simulated_revenue, "PR358_SIMULATED_REVENUE_NEGATIVE")
    _nonnegative(total_cost, "PR358_TOTAL_COST_NEGATIVE")
    return {
        "simulated_margin": simulated_revenue - total_cost,
        "break_even": simulated_revenue >= total_cost,
        "customer_billing": False,
    }


def measure_product_portfolio_value(
    values: Mapping[str, int],
) -> Mapping[str, Any]:
    return {
        "service_values": dict(sorted(values.items())),
        "simulated_total_value": sum(values.values()),
        "realized_revenue_claimed": False,
    }


def effect_boundary() -> Mapping[str, bool]:
    return dict(EFFECT_BOUNDARY)


def deterministic_receipt(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    body = dict(payload)
    body["execution_right"] = False
    body["receipt_hash"] = canonical_hash(body)
    return body
