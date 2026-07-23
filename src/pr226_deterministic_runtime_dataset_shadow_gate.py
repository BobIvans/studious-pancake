"""PR-226 deterministic runtime, dataset and shadow qualification gate.

This module is intentionally offline and side-effect free. It validates the
materialized evidence contract for the sender-free opportunity runtime, decision
dataset, model gate and shadow qualification boundary from audit Pass 8/9.

It does not import providers, read secrets, sign, submit, open sockets, call RPC,
or enable live trading.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from math import isfinite
import re
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = "pr226.deterministic-runtime-dataset-shadow-gate.v1"
ROADMAP_ID = "PR-226"
REQUIRED_DEPENDENCIES = ("PR-225", "PR-227")
REQUIRED_FINDINGS = frozenset(
    [*(f"F-{number:03d}" for number in range(355, 387)), *(f"F-{number:03d}" for number in range(404, 410))]
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class PR226Violation:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class PR226Report:
    schema_version: str
    roadmap: str
    decision: str
    blockers: tuple[PR226Violation, ...]
    evidence_hash: str
    sender_free_shadow_qualified: bool
    dataset_promotion_allowed: bool
    model_promotion_allowed: bool
    live_execution_allowed: bool
    signer_allowed: bool
    sender_allowed: bool
    private_key_allowed: bool

    @property
    def ok(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "roadmap": self.roadmap,
            "decision": self.decision,
            "blockers": [
                {"code": blocker.code, "detail": blocker.detail}
                for blocker in self.blockers
            ],
            "evidence_hash": self.evidence_hash,
            "sender_free_shadow_qualified": self.sender_free_shadow_qualified,
            "dataset_promotion_allowed": self.dataset_promotion_allowed,
            "model_promotion_allowed": self.model_promotion_allowed,
            "live_execution_allowed": self.live_execution_allowed,
            "signer_allowed": self.signer_allowed,
            "sender_allowed": self.sender_allowed,
            "private_key_allowed": self.private_key_allowed,
        }


def evaluate_pr226_shadow_qualification_evidence(
    evidence: Mapping[str, Any],
) -> PR226Report:
    """Evaluate a PR-226 sender-free shadow/runtime qualification bundle."""

    blockers: list[PR226Violation] = []

    if evidence.get("schema_version") != SCHEMA_VERSION:
        _add(blockers, "PR226_SCHEMA_VERSION", "schema_version must match PR-226 contract")
    if evidence.get("roadmap") != ROADMAP_ID:
        _add(blockers, "PR226_ROADMAP", "roadmap must be PR-226")

    _validate_dependencies(_mapping(evidence.get("dependencies")), blockers)
    _validate_findings(evidence.get("findings_covered", ()), blockers)
    _validate_no_forbidden_surfaces(evidence, blockers)
    _validate_opportunity_domain(_mapping(evidence.get("opportunity_domain")), blockers)
    _validate_queue_runtime(_mapping(evidence.get("queue_runtime")), blockers)
    _validate_terminal_protocol(_mapping(evidence.get("terminal_protocol")), blockers)
    _validate_supervision(_mapping(evidence.get("supervision")), blockers)
    _validate_dataset(_mapping(evidence.get("dataset")), blockers)
    _validate_publication(_mapping(evidence.get("publication")), blockers)
    _validate_split_and_model(_mapping(evidence.get("split_model_gate")), blockers)
    _validate_runtime_namespace(_mapping(evidence.get("runtime_namespace")), blockers)
    _validate_artifacts(_mapping(evidence.get("artifacts")), blockers)

    unique = tuple(_dedupe(blockers))
    accepted = not unique
    return PR226Report(
        schema_version=SCHEMA_VERSION,
        roadmap=ROADMAP_ID,
        decision="sender_free_shadow_qualified" if accepted else "blocked",
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        sender_free_shadow_qualified=accepted,
        dataset_promotion_allowed=accepted,
        model_promotion_allowed=accepted,
        live_execution_allowed=False,
        signer_allowed=False,
        sender_allowed=False,
        private_key_allowed=False,
    )


def report_to_json(report: PR226Report) -> str:
    return json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def blockers_by_code(report: PR226Report) -> dict[str, PR226Violation]:
    return {blocker.code: blocker for blocker in report.blockers}


def _validate_dependencies(
    dependencies: Mapping[str, Any], blockers: list[PR226Violation]
) -> None:
    for dependency in REQUIRED_DEPENDENCIES:
        item = _mapping(dependencies.get(dependency))
        if not item.get("accepted"):
            _add(blockers, "PR226_DEPENDENCY_NOT_ACCEPTED", f"{dependency} is not accepted")
        if not item.get("installed_artifact_reachable"):
            _add(blockers, "PR226_DEPENDENCY_NOT_REACHABLE", f"{dependency} is not in installed graph")
        if not _sha256(item.get("evidence_hash")):
            _add(blockers, "PR226_DEPENDENCY_BAD_HASH", f"{dependency} evidence_hash must be SHA-256")


def _validate_findings(findings: Any, blockers: list[PR226Violation]) -> None:
    values = tuple(str(item) for item in _sequence(findings))
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in values:
        if item in seen:
            duplicates.add(item)
        seen.add(item)
    missing = sorted(REQUIRED_FINDINGS.difference(seen))
    unknown = sorted(seen.difference(REQUIRED_FINDINGS))
    if missing:
        _add(blockers, "PR226_MISSING_FINDING_COVERAGE", ",".join(missing))
    if unknown:
        _add(blockers, "PR226_UNKNOWN_FINDING_COVERAGE", ",".join(unknown))
    if duplicates:
        _add(blockers, "PR226_DUPLICATE_FINDING_COVERAGE", ",".join(sorted(duplicates)))


def _validate_no_forbidden_surfaces(
    evidence: Mapping[str, Any], blockers: list[PR226Violation]
) -> None:
    for key in (
        "live_execution_enabled",
        "signer_enabled",
        "sender_enabled",
        "private_key_loaded",
        "real_submission_enabled",
        "jito_submission_enabled",
    ):
        if bool(evidence.get(key)):
            _add(blockers, "PR226_FORBIDDEN_RUNTIME_SURFACE", key)


def _validate_opportunity_domain(
    domain: Mapping[str, Any], blockers: list[PR226Violation]
) -> None:
    required = {
        "rejects_nan_infinity": "PR226_OPPORTUNITY_NONFINITE",
        "rejects_bool_integer_fields": "PR226_OPPORTUNITY_BOOL_AS_INT",
        "rejects_fractional_base_units": "PR226_OPPORTUNITY_FRACTIONAL_UNITS",
        "rejects_negative_slots": "PR226_OPPORTUNITY_NEGATIVE_SLOT",
        "deep_freezes_nested_metadata": "PR226_OPPORTUNITY_MUTABLE_METADATA",
        "identity_binds_strategy_provider_evidence_generation": "PR226_OPPORTUNITY_IDENTITY",
        "canonical_hash_without_default_str": "PR226_OPPORTUNITY_DEFAULT_STR",
    }
    for key, code in required.items():
        if domain.get(key) is not True:
            _add(blockers, code, key)
    if not _positive_int(domain.get("identity_generation")):
        _add(blockers, "PR226_OPPORTUNITY_IDENTITY_GENERATION", "identity_generation must be positive int")


def _validate_queue_runtime(
    runtime: Mapping[str, Any], blockers: list[PR226Violation]
) -> None:
    required = {
        "rechecks_expiry_after_every_await": "PR226_QUEUE_EXPIRY_AFTER_AWAIT",
        "rechecks_expiry_before_enqueue": "PR226_QUEUE_EXPIRY_BEFORE_ENQUEUE",
        "rechecks_expiry_before_claim": "PR226_QUEUE_EXPIRY_BEFORE_CLAIM",
        "deterministic_tie_breakers": "PR226_QUEUE_NONDETERMINISTIC_TIES",
        "replacement_priority_documented": "PR226_QUEUE_REPLACEMENT_UNDOCUMENTED",
        "bounded_queue": "PR226_QUEUE_UNBOUNDED",
        "cancellation_releases_claim": "PR226_QUEUE_CANCEL_LEAKS_CLAIM",
    }
    for key, code in required.items():
        if runtime.get(key) is not True:
            _add(blockers, code, key)
    max_size = runtime.get("max_size")
    if not _positive_int(max_size) or int(max_size) > 10000:
        _add(blockers, "PR226_QUEUE_BAD_MAX_SIZE", "max_size must be positive and bounded")


def _validate_terminal_protocol(
    terminal: Mapping[str, Any], blockers: list[PR226Violation]
) -> None:
    required = {
        "result_binds_opportunity_id": "PR226_TERMINAL_RESULT_IDENTITY",
        "result_binds_strategy_id": "PR226_TERMINAL_RESULT_STRATEGY",
        "durable_sink_commit_before_terminal": "PR226_TERMINAL_SINK_ORDER",
        "sink_failure_blocks_terminal_success": "PR226_TERMINAL_SINK_FAILURE_SUCCESS",
        "duplicate_claim_writes_audit_evidence": "PR226_TERMINAL_DUPLICATE_AUDIT",
        "conflicting_result_rejected": "PR226_TERMINAL_CONFLICT_REJECTED",
        "terminal_state_exactly_once": "PR226_TERMINAL_NOT_EXACTLY_ONCE",
    }
    for key, code in required.items():
        if terminal.get(key) is not True:
            _add(blockers, code, key)


def _validate_supervision(
    supervision: Mapping[str, Any], blockers: list[PR226Violation]
) -> None:
    required = {
        "supervisor_owns_all_strategy_tasks": "PR226_SUPERVISION_TASK_OWNERSHIP",
        "consumer_task_death_blocks_readiness": "PR226_SUPERVISION_CONSUMER_DEATH",
        "strategy_task_death_blocks_readiness": "PR226_SUPERVISION_STRATEGY_DEATH",
        "started_requires_live_strategy_count": "PR226_SUPERVISION_ZERO_STRATEGIES",
        "shutdown_records_terminal_evidence": "PR226_SUPERVISION_SHUTDOWN_EVIDENCE",
        "strategy_stop_errors_materialized": "PR226_SUPERVISION_STOP_ERRORS",
    }
    for key, code in required.items():
        if supervision.get(key) is not True:
            _add(blockers, code, key)
    for key in ("handler_deadline_seconds", "sink_deadline_seconds", "shutdown_deadline_seconds"):
        if not _finite_positive_number(supervision.get(key)):
            _add(blockers, "PR226_SUPERVISION_BAD_DEADLINE", key)


def _validate_dataset(dataset: Mapping[str, Any], blockers: list[PR226Violation]) -> None:
    required = {
        "label_from_terminal_event_before_cutoff": "PR226_DATASET_TEMPORAL_LEAKAGE",
        "future_terminal_outcomes_rejected": "PR226_DATASET_FUTURE_OUTCOME",
        "label_provenance_event_hash_bound": "PR226_DATASET_LABEL_PROVENANCE",
        "correction_lineage_preserved": "PR226_DATASET_CORRECTION_LINEAGE",
        "utc_aware_timestamps_only": "PR226_DATASET_NAIVE_TIME",
        "deterministic_event_ordering": "PR226_DATASET_ORDERING",
        "duplicate_file_ingestion_idempotent": "PR226_DATASET_DUPLICATE_FILE",
        "row_schema_validated_deeply": "PR226_DATASET_ROW_SCHEMA",
    }
    for key, code in required.items():
        if dataset.get(key) is not True:
            _add(blockers, code, key)


def _validate_publication(
    publication: Mapping[str, Any], blockers: list[PR226Violation]
) -> None:
    required = {
        "atomic_generation_publish": "PR226_PUBLICATION_NOT_ATOMIC",
        "rows_manifest_split_same_generation": "PR226_PUBLICATION_MIXED_GENERATION",
        "loader_rehashes_rows_manifest_split": "PR226_PUBLICATION_LOADER_NO_REHASH",
        "immutable_generation": "PR226_PUBLICATION_MUTABLE_GENERATION",
        "schema_hash_bound": "PR226_PUBLICATION_SCHEMA_UNBOUND",
        "no_default_str_canonicalization": "PR226_PUBLICATION_DEFAULT_STR",
    }
    for key, code in required.items():
        if publication.get(key) is not True:
            _add(blockers, code, key)
    if not _sha256(publication.get("generation_hash")):
        _add(blockers, "PR226_PUBLICATION_BAD_GENERATION_HASH", "generation_hash must be SHA-256")


def _validate_split_and_model(
    split_model: Mapping[str, Any], blockers: list[PR226Violation]
) -> None:
    required = {
        "group_temporal_split": "PR226_SPLIT_NOT_GROUP_TEMPORAL",
        "no_future_group_rows_in_train": "PR226_SPLIT_GROUP_LEAKAGE",
        "fractions_validated": "PR226_SPLIT_BAD_FRACTIONS",
        "embargo_validated": "PR226_SPLIT_BAD_EMBARGO",
        "split_manifest_bound_to_dataset_hash": "PR226_SPLIT_MANIFEST_UNBOUND",
        "real_metrics_required": "PR226_MODEL_FAKE_METRICS",
        "undefined_metrics_block_promotion": "PR226_MODEL_UNDEFINED_METRICS",
        "ood_range_gate": "PR226_MODEL_NO_OOD_GATE",
        "no_hardcoded_safety_conclusions": "PR226_MODEL_HARDCODED_SAFETY",
    }
    for key, code in required.items():
        if split_model.get(key) is not True:
            _add(blockers, code, key)
    if not _positive_int(split_model.get("minimum_training_rows")) or int(split_model["minimum_training_rows"]) < 100:
        _add(blockers, "PR226_MODEL_TOO_SMALL", "minimum_training_rows must be >= 100")
    if not _sha256(split_model.get("dataset_hash")):
        _add(blockers, "PR226_SPLIT_BAD_DATASET_HASH", "dataset_hash must be SHA-256")


def _validate_runtime_namespace(
    namespace: Mapping[str, Any], blockers: list[PR226Violation]
) -> None:
    required = {
        "finite_numeric_config": "PR226_RUNTIME_NONFINITE_CONFIG",
        "rejects_nan_idle_delay": "PR226_RUNTIME_NAN_IDLE_DELAY",
        "unique_process_owner_id": "PR226_RUNTIME_DEFAULT_OWNER",
        "absolute_generation_bound_state_paths": "PR226_RUNTIME_CWD_DEPENDENCE",
        "no_shared_tmp_secret_namespace": "PR226_RUNTIME_SHARED_TMP_SECRET",
        "python_optimized_mode_safe": "PR226_RUNTIME_PRODUCTION_ASSERT",
        "single_runtime_owner_per_state_path": "PR226_RUNTIME_MULTI_OWNER_PATH",
    }
    for key, code in required.items():
        if namespace.get(key) is not True:
            _add(blockers, code, key)


def _validate_artifacts(artifacts: Mapping[str, Any], blockers: list[PR226Violation]) -> None:
    required = {
        "runtime_trace_hash": "PR226_ARTIFACT_BAD_RUNTIME_TRACE",
        "terminal_event_hash": "PR226_ARTIFACT_BAD_TERMINAL_EVENT",
        "dataset_generation_hash": "PR226_ARTIFACT_BAD_DATASET_GENERATION",
        "split_manifest_hash": "PR226_ARTIFACT_BAD_SPLIT_MANIFEST",
        "shadow_qualification_hash": "PR226_ARTIFACT_BAD_SHADOW_QUALIFICATION",
    }
    for key, code in required.items():
        if not _sha256(artifacts.get(key)):
            _add(blockers, code, key)
    if artifacts.get("materialized_from_installed_wheel") is not True:
        _add(blockers, "PR226_ARTIFACT_NOT_INSTALLED_WHEEL", "materialized_from_installed_wheel")
    if artifacts.get("black_box_trace_replayable") is not True:
        _add(blockers, "PR226_ARTIFACT_TRACE_NOT_REPLAYABLE", "black_box_trace_replayable")
    if artifacts.get("crash_restart_proof") is not True:
        _add(blockers, "PR226_ARTIFACT_NO_CRASH_RESTART_PROOF", "crash_restart_proof")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return ()
    return value


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _finite_positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value > 0


def _stable_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _json_safe(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if isfinite(value):
            return value
        return {"__non_finite_float__": repr(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in sorted(value.items(), key=lambda entry: str(entry[0]))}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    return {"__non_json_value__": type(value).__name__}


def _add(blockers: list[PR226Violation], code: str, detail: str) -> None:
    blockers.append(PR226Violation(code=code, detail=detail))


def _dedupe(blockers: Iterable[PR226Violation]) -> list[PR226Violation]:
    seen: set[tuple[str, str]] = set()
    result: list[PR226Violation] = []
    for blocker in blockers:
        key = (blocker.code, blocker.detail)
        if key not in seen:
            result.append(blocker)
            seen.add(key)
    return result


__all__ = [
    "ROADMAP_ID",
    "REQUIRED_DEPENDENCIES",
    "REQUIRED_FINDINGS",
    "SCHEMA_VERSION",
    "PR226Report",
    "PR226Violation",
    "blockers_by_code",
    "evaluate_pr226_shadow_qualification_evidence",
    "report_to_json",
]
