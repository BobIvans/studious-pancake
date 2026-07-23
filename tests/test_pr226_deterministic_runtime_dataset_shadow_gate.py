from __future__ import annotations

from copy import deepcopy
import math

from src.pr226_deterministic_runtime_dataset_shadow_gate import (
    REQUIRED_FINDINGS,
    SCHEMA_VERSION,
    blockers_by_code,
    evaluate_pr226_shadow_qualification_evidence,
    report_to_json,
)


HASH = "a" * 64


def valid_evidence() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "roadmap": "PR-226",
        "dependencies": {
            "PR-225": {
                "accepted": True,
                "installed_artifact_reachable": True,
                "evidence_hash": HASH,
            },
            "PR-227": {
                "accepted": True,
                "installed_artifact_reachable": True,
                "evidence_hash": HASH,
            },
        },
        "findings_covered": sorted(REQUIRED_FINDINGS),
        "live_execution_enabled": False,
        "signer_enabled": False,
        "sender_enabled": False,
        "private_key_loaded": False,
        "real_submission_enabled": False,
        "jito_submission_enabled": False,
        "opportunity_domain": {
            "rejects_nan_infinity": True,
            "rejects_bool_integer_fields": True,
            "rejects_fractional_base_units": True,
            "rejects_negative_slots": True,
            "deep_freezes_nested_metadata": True,
            "identity_binds_strategy_provider_evidence_generation": True,
            "canonical_hash_without_default_str": True,
            "identity_generation": 7,
        },
        "queue_runtime": {
            "rechecks_expiry_after_every_await": True,
            "rechecks_expiry_before_enqueue": True,
            "rechecks_expiry_before_claim": True,
            "deterministic_tie_breakers": True,
            "replacement_priority_documented": True,
            "bounded_queue": True,
            "cancellation_releases_claim": True,
            "max_size": 128,
        },
        "terminal_protocol": {
            "result_binds_opportunity_id": True,
            "result_binds_strategy_id": True,
            "durable_sink_commit_before_terminal": True,
            "sink_failure_blocks_terminal_success": True,
            "duplicate_claim_writes_audit_evidence": True,
            "conflicting_result_rejected": True,
            "terminal_state_exactly_once": True,
        },
        "supervision": {
            "supervisor_owns_all_strategy_tasks": True,
            "consumer_task_death_blocks_readiness": True,
            "strategy_task_death_blocks_readiness": True,
            "started_requires_live_strategy_count": True,
            "shutdown_records_terminal_evidence": True,
            "strategy_stop_errors_materialized": True,
            "handler_deadline_seconds": 5.0,
            "sink_deadline_seconds": 5.0,
            "shutdown_deadline_seconds": 30.0,
        },
        "dataset": {
            "label_from_terminal_event_before_cutoff": True,
            "future_terminal_outcomes_rejected": True,
            "label_provenance_event_hash_bound": True,
            "correction_lineage_preserved": True,
            "utc_aware_timestamps_only": True,
            "deterministic_event_ordering": True,
            "duplicate_file_ingestion_idempotent": True,
            "row_schema_validated_deeply": True,
        },
        "publication": {
            "atomic_generation_publish": True,
            "rows_manifest_split_same_generation": True,
            "loader_rehashes_rows_manifest_split": True,
            "immutable_generation": True,
            "schema_hash_bound": True,
            "no_default_str_canonicalization": True,
            "generation_hash": HASH,
        },
        "split_model_gate": {
            "group_temporal_split": True,
            "no_future_group_rows_in_train": True,
            "fractions_validated": True,
            "embargo_validated": True,
            "split_manifest_bound_to_dataset_hash": True,
            "real_metrics_required": True,
            "undefined_metrics_block_promotion": True,
            "ood_range_gate": True,
            "no_hardcoded_safety_conclusions": True,
            "minimum_training_rows": 1000,
            "dataset_hash": HASH,
        },
        "runtime_namespace": {
            "finite_numeric_config": True,
            "rejects_nan_idle_delay": True,
            "unique_process_owner_id": True,
            "absolute_generation_bound_state_paths": True,
            "no_shared_tmp_secret_namespace": True,
            "python_optimized_mode_safe": True,
            "single_runtime_owner_per_state_path": True,
        },
        "artifacts": {
            "runtime_trace_hash": HASH,
            "terminal_event_hash": HASH,
            "dataset_generation_hash": HASH,
            "split_manifest_hash": HASH,
            "shadow_qualification_hash": HASH,
            "materialized_from_installed_wheel": True,
            "black_box_trace_replayable": True,
            "crash_restart_proof": True,
        },
    }


def codes(evidence: dict[str, object]) -> set[str]:
    return set(blockers_by_code(evaluate_pr226_shadow_qualification_evidence(evidence)))


def test_complete_sender_free_shadow_evidence_is_qualified_but_not_live() -> None:
    report = evaluate_pr226_shadow_qualification_evidence(valid_evidence())

    assert report.ok
    assert report.decision == "sender_free_shadow_qualified"
    assert report.sender_free_shadow_qualified
    assert report.dataset_promotion_allowed
    assert report.model_promotion_allowed
    assert not report.live_execution_allowed
    assert not report.signer_allowed
    assert not report.sender_allowed
    assert not report.private_key_allowed


def test_missing_upstream_pr225_or_pr227_blocks_qualification() -> None:
    evidence = valid_evidence()
    dependencies = deepcopy(evidence["dependencies"])
    dependencies["PR-225"]["accepted"] = False
    dependencies["PR-227"]["installed_artifact_reachable"] = False
    dependencies["PR-227"]["evidence_hash"] = "not-a-hash"
    evidence["dependencies"] = dependencies

    assert codes(evidence) >= {
        "PR226_DEPENDENCY_NOT_ACCEPTED",
        "PR226_DEPENDENCY_NOT_REACHABLE",
        "PR226_DEPENDENCY_BAD_HASH",
    }


def test_findings_must_match_pr226_ownership_exactly_once() -> None:
    evidence = valid_evidence()
    covered = sorted(REQUIRED_FINDINGS)
    evidence["findings_covered"] = [*covered[1:], covered[-1], "F-225"]

    assert codes(evidence) >= {
        "PR226_MISSING_FINDING_COVERAGE",
        "PR226_UNKNOWN_FINDING_COVERAGE",
        "PR226_DUPLICATE_FINDING_COVERAGE",
    }


def test_opportunity_domain_rejects_nonfinite_bool_fractional_and_mutable_metadata() -> None:
    evidence = valid_evidence()
    domain = deepcopy(evidence["opportunity_domain"])
    domain["rejects_nan_infinity"] = False
    domain["rejects_bool_integer_fields"] = False
    domain["rejects_fractional_base_units"] = False
    domain["deep_freezes_nested_metadata"] = False
    domain["identity_generation"] = True
    evidence["opportunity_domain"] = domain

    assert codes(evidence) >= {
        "PR226_OPPORTUNITY_NONFINITE",
        "PR226_OPPORTUNITY_BOOL_AS_INT",
        "PR226_OPPORTUNITY_FRACTIONAL_UNITS",
        "PR226_OPPORTUNITY_MUTABLE_METADATA",
        "PR226_OPPORTUNITY_IDENTITY_GENERATION",
    }


def test_queue_runtime_requires_expiry_rechecks_after_await_and_before_claim() -> None:
    evidence = valid_evidence()
    queue = deepcopy(evidence["queue_runtime"])
    queue["rechecks_expiry_after_every_await"] = False
    queue["rechecks_expiry_before_claim"] = False
    queue["deterministic_tie_breakers"] = False
    queue["max_size"] = 0
    evidence["queue_runtime"] = queue

    assert codes(evidence) >= {
        "PR226_QUEUE_EXPIRY_AFTER_AWAIT",
        "PR226_QUEUE_EXPIRY_BEFORE_CLAIM",
        "PR226_QUEUE_NONDETERMINISTIC_TIES",
        "PR226_QUEUE_BAD_MAX_SIZE",
    }


def test_terminal_success_requires_durable_sink_commit_and_identity_binding() -> None:
    evidence = valid_evidence()
    terminal = deepcopy(evidence["terminal_protocol"])
    terminal["result_binds_opportunity_id"] = False
    terminal["durable_sink_commit_before_terminal"] = False
    terminal["sink_failure_blocks_terminal_success"] = False
    terminal["conflicting_result_rejected"] = False
    evidence["terminal_protocol"] = terminal

    assert codes(evidence) >= {
        "PR226_TERMINAL_RESULT_IDENTITY",
        "PR226_TERMINAL_SINK_ORDER",
        "PR226_TERMINAL_SINK_FAILURE_SUCCESS",
        "PR226_TERMINAL_CONFLICT_REJECTED",
    }


def test_supervision_blocks_on_task_death_zero_strategies_and_bad_deadlines() -> None:
    evidence = valid_evidence()
    supervision = deepcopy(evidence["supervision"])
    supervision["consumer_task_death_blocks_readiness"] = False
    supervision["strategy_task_death_blocks_readiness"] = False
    supervision["started_requires_live_strategy_count"] = False
    supervision["handler_deadline_seconds"] = math.nan
    supervision["sink_deadline_seconds"] = True
    evidence["supervision"] = supervision

    assert codes(evidence) >= {
        "PR226_SUPERVISION_CONSUMER_DEATH",
        "PR226_SUPERVISION_STRATEGY_DEATH",
        "PR226_SUPERVISION_ZERO_STRATEGIES",
        "PR226_SUPERVISION_BAD_DEADLINE",
    }


def test_dataset_labels_cannot_read_future_terminal_outcomes() -> None:
    evidence = valid_evidence()
    dataset = deepcopy(evidence["dataset"])
    dataset["label_from_terminal_event_before_cutoff"] = False
    dataset["future_terminal_outcomes_rejected"] = False
    dataset["label_provenance_event_hash_bound"] = False
    dataset["duplicate_file_ingestion_idempotent"] = False
    evidence["dataset"] = dataset

    assert codes(evidence) >= {
        "PR226_DATASET_TEMPORAL_LEAKAGE",
        "PR226_DATASET_FUTURE_OUTCOME",
        "PR226_DATASET_LABEL_PROVENANCE",
        "PR226_DATASET_DUPLICATE_FILE",
    }


def test_dataset_publication_is_one_atomic_generation_without_default_str() -> None:
    evidence = valid_evidence()
    publication = deepcopy(evidence["publication"])
    publication["atomic_generation_publish"] = False
    publication["rows_manifest_split_same_generation"] = False
    publication["no_default_str_canonicalization"] = False
    publication["generation_hash"] = "0" * 63
    evidence["publication"] = publication

    assert codes(evidence) >= {
        "PR226_PUBLICATION_NOT_ATOMIC",
        "PR226_PUBLICATION_MIXED_GENERATION",
        "PR226_PUBLICATION_DEFAULT_STR",
        "PR226_PUBLICATION_BAD_GENERATION_HASH",
    }


def test_split_and_model_gate_blocks_leakage_small_data_and_fake_metrics() -> None:
    evidence = valid_evidence()
    split = deepcopy(evidence["split_model_gate"])
    split["group_temporal_split"] = False
    split["no_future_group_rows_in_train"] = False
    split["real_metrics_required"] = False
    split["undefined_metrics_block_promotion"] = False
    split["ood_range_gate"] = False
    split["minimum_training_rows"] = 12
    split["dataset_hash"] = "bad"
    evidence["split_model_gate"] = split

    assert codes(evidence) >= {
        "PR226_SPLIT_NOT_GROUP_TEMPORAL",
        "PR226_SPLIT_GROUP_LEAKAGE",
        "PR226_MODEL_FAKE_METRICS",
        "PR226_MODEL_UNDEFINED_METRICS",
        "PR226_MODEL_NO_OOD_GATE",
        "PR226_MODEL_TOO_SMALL",
        "PR226_SPLIT_BAD_DATASET_HASH",
    }


def test_runtime_namespace_blocks_shared_tmp_cwd_default_owner_and_assert_semantics() -> None:
    evidence = valid_evidence()
    namespace = deepcopy(evidence["runtime_namespace"])
    namespace["unique_process_owner_id"] = False
    namespace["absolute_generation_bound_state_paths"] = False
    namespace["no_shared_tmp_secret_namespace"] = False
    namespace["python_optimized_mode_safe"] = False
    evidence["runtime_namespace"] = namespace

    assert codes(evidence) >= {
        "PR226_RUNTIME_DEFAULT_OWNER",
        "PR226_RUNTIME_CWD_DEPENDENCE",
        "PR226_RUNTIME_SHARED_TMP_SECRET",
        "PR226_RUNTIME_PRODUCTION_ASSERT",
    }


def test_shadow_evidence_must_be_materialized_from_installed_wheel_and_replayable() -> None:
    evidence = valid_evidence()
    artifacts = deepcopy(evidence["artifacts"])
    artifacts["runtime_trace_hash"] = "trace"
    artifacts["materialized_from_installed_wheel"] = False
    artifacts["black_box_trace_replayable"] = False
    artifacts["crash_restart_proof"] = False
    evidence["artifacts"] = artifacts

    assert codes(evidence) >= {
        "PR226_ARTIFACT_BAD_RUNTIME_TRACE",
        "PR226_ARTIFACT_NOT_INSTALLED_WHEEL",
        "PR226_ARTIFACT_TRACE_NOT_REPLAYABLE",
        "PR226_ARTIFACT_NO_CRASH_RESTART_PROOF",
    }


def test_forbidden_live_signer_sender_private_key_surfaces_always_block() -> None:
    evidence = valid_evidence()
    evidence["live_execution_enabled"] = True
    evidence["signer_enabled"] = True
    evidence["sender_enabled"] = True
    evidence["private_key_loaded"] = True

    report = evaluate_pr226_shadow_qualification_evidence(evidence)

    assert not report.ok
    assert "PR226_FORBIDDEN_RUNTIME_SURFACE" in codes(evidence)
    assert not report.live_execution_allowed
    assert not report.signer_allowed
    assert not report.sender_allowed
    assert not report.private_key_allowed


def test_report_json_is_deterministic_and_sorted() -> None:
    left = report_to_json(evaluate_pr226_shadow_qualification_evidence(valid_evidence()))
    right = report_to_json(evaluate_pr226_shadow_qualification_evidence(valid_evidence()))

    assert left == right
    assert '"decision":"sender_free_shadow_qualified"' in left
    assert '"live_execution_allowed":false' in left
