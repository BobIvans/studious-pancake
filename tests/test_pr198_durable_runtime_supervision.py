from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.paper_shadow.durable_runtime_supervision_pr198 import (
    QueueLifecycleEvidence,
    RuntimeDependencyEvidence,
    RuntimeSupervisionEvidenceBundle,
    ShutdownDrainEvidence,
    StrategyTaskEvidence,
    evaluate_runtime_supervision_evidence,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
COMMIT = "1" * 40
ASSEMBLED_AT = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)


def _dependencies(**overrides: object) -> RuntimeDependencyEvidence:
    values = {
        "production_factory_singleton": True,
        "installed_command_singleton": True,
        "real_dependency_graph": True,
        "placeholder_dependencies_present": False,
        "memory_only_authorities_present": False,
        "dependency_graph_hash": DIGEST_A,
    }
    values.update(overrides)
    return RuntimeDependencyEvidence(**values)


def _strategy(**overrides: object) -> StrategyTaskEvidence:
    values = {
        "strategy_name": "rooted-opportunity-detector",
        "required": True,
        "supervised": True,
        "state": "running",
        "readiness_false_on_failure": True,
        "restart_attempts": 0,
        "restart_limit": 3,
        "terminal_reason_code": "",
        "exception_redacted": True,
    }
    values.update(overrides)
    return StrategyTaskEvidence(**values)


def _queue(**overrides: object) -> QueueLifecycleEvidence:
    values = {
        "durable_queue": True,
        "admission_closed_before_drain": True,
        "single_consumer_owner": True,
        "expiry_releases_pending_lifecycle": True,
        "tracker_state_durable": True,
        "result_sink_durable": True,
        "duplicate_processing_observed": False,
        "max_queue_depth": 128,
        "pending_items_at_shutdown": 3,
        "terminal_outcomes_written": 2,
        "abandoned_or_requeued_items": 1,
    }
    values.update(overrides)
    return QueueLifecycleEvidence(**values)


def _shutdown(**overrides: object) -> ShutdownDrainEvidence:
    values = {
        "structured_concurrency": True,
        "deadline_ms": 30_000,
        "fallback_deadline_ms": 5_000,
        "cancellation_acknowledged": True,
        "owned_tasks_before_shutdown": 4,
        "owned_tasks_after_shutdown": 0,
        "double_consumer_race_prevented": True,
        "forced_shutdown_latch_written": True,
        "terminal_queue_action": "durable-requeue-written",
    }
    values.update(overrides)
    return ShutdownDrainEvidence(**values)


def _bundle(**overrides: object) -> RuntimeSupervisionEvidenceBundle:
    values = {
        "source_commit": COMMIT,
        "dependencies": _dependencies(),
        "strategies": (_strategy(),),
        "queue": _queue(),
        "shutdown": _shutdown(),
        "active_surface": (),
        "evidence_artifacts": {
            "runtime_trace_sha256": DIGEST_A,
            "shutdown_trace_sha256": DIGEST_B,
            "queue_lifecycle_sha256": DIGEST_C,
        },
        "assembled_at": ASSEMBLED_AT,
        "assembled_by": "runtime-assurance@example.com",
    }
    values.update(overrides)
    return RuntimeSupervisionEvidenceBundle(**values)


def test_runtime_supervision_ready_is_sender_free_only() -> None:
    report = evaluate_runtime_supervision_evidence(_bundle())

    assert report.ready_for_sender_free_shadow is True
    assert report.live_execution_allowed is False
    assert report.sender_import_allowed is False
    assert report.signing_allowed is False
    assert report.blockers == ()
    assert report.state.value == "ready-for-sender-free-shadow"
    assert report.evidence_hash


def test_placeholder_or_memory_only_authorities_block_installed_vertical() -> None:
    report = evaluate_runtime_supervision_evidence(
        _bundle(
            dependencies=_dependencies(
                production_factory_singleton=False,
                installed_command_singleton=False,
                real_dependency_graph=False,
                placeholder_dependencies_present=True,
                memory_only_authorities_present=True,
            )
        )
    )

    assert "PRODUCTION_FACTORY_NOT_SINGLETON" in report.blockers
    assert "INSTALLED_COMMAND_NOT_SINGLETON" in report.blockers
    assert "REAL_DEPENDENCY_GRAPH_MISSING" in report.blockers
    assert "PLACEHOLDER_DEPENDENCIES_PRESENT" in report.blockers
    assert "MEMORY_ONLY_AUTHORITIES_PRESENT" in report.blockers


def test_required_strategy_failure_must_drop_readiness_and_be_redacted() -> None:
    report = evaluate_runtime_supervision_evidence(
        _bundle(
            strategies=(
                _strategy(
                    state="failed",
                    readiness_false_on_failure=False,
                    terminal_reason_code="",
                    exception_redacted=False,
                ),
            )
        )
    )

    assert (
        "REQUIRED_STRATEGY_NOT_HEALTHY:rooted-opportunity-detector"
        in report.blockers
    )
    assert (
        "STRATEGY_FAILURE_NOT_READINESS_FALSE:rooted-opportunity-detector"
        in report.blockers
    )
    assert (
        "STRATEGY_FAILURE_REASON_MISSING:rooted-opportunity-detector"
        in report.blockers
    )
    assert (
        "STRATEGY_FAILURE_EXCEPTION_NOT_REDACTED:rooted-opportunity-detector"
        in report.blockers
    )


def test_queue_expiry_shutdown_and_terminal_outcomes_are_blocking() -> None:
    report = evaluate_runtime_supervision_evidence(
        _bundle(
            queue=_queue(
                durable_queue=False,
                admission_closed_before_drain=False,
                single_consumer_owner=False,
                expiry_releases_pending_lifecycle=False,
                tracker_state_durable=False,
                result_sink_durable=False,
                duplicate_processing_observed=True,
                max_queue_depth=0,
                pending_items_at_shutdown=4,
                terminal_outcomes_written=1,
                abandoned_or_requeued_items=1,
            )
        )
    )

    assert "QUEUE_NOT_DURABLE" in report.blockers
    assert "ADMISSION_NOT_CLOSED_BEFORE_DRAIN" in report.blockers
    assert "SHUTDOWN_DRAIN_HAS_DOUBLE_CONSUMER_RISK" in report.blockers
    assert "EXPIRY_DOES_NOT_RELEASE_PENDING_LIFECYCLE" in report.blockers
    assert "TRACKER_STATE_NOT_DURABLE" in report.blockers
    assert "RESULT_SINK_NOT_DURABLE" in report.blockers
    assert "DUPLICATE_PROCESSING_OBSERVED" in report.blockers
    assert "QUEUE_MAX_DEPTH_NOT_SET" in report.blockers
    assert "SHUTDOWN_PENDING_ITEMS_NOT_TERMINALIZED" in report.blockers


def test_shutdown_fallback_must_be_bounded_and_leave_no_owned_tasks() -> None:
    report = evaluate_runtime_supervision_evidence(
        _bundle(
            shutdown=_shutdown(
                structured_concurrency=False,
                deadline_ms=120_000,
                fallback_deadline_ms=130_000,
                cancellation_acknowledged=False,
                owned_tasks_before_shutdown=2,
                owned_tasks_after_shutdown=3,
                double_consumer_race_prevented=False,
                forced_shutdown_latch_written=False,
            )
        )
    )

    assert "STRUCTURED_CONCURRENCY_MISSING" in report.blockers
    assert "SHUTDOWN_DEADLINE_TOO_LARGE" in report.blockers
    assert "SHUTDOWN_FALLBACK_NOT_BOUNDED_BY_DEADLINE" in report.blockers
    assert "CANCELLATION_NOT_ACKNOWLEDGED" in report.blockers
    assert "OWNED_TASKS_LEFT_RUNNING_AFTER_SHUTDOWN" in report.blockers
    assert "OWNED_TASK_COUNT_INCREASED_DURING_SHUTDOWN" in report.blockers
    assert "DOUBLE_CONSUMER_RACE_NOT_PREVENTED" in report.blockers
    assert "FORCED_SHUTDOWN_LATCH_MISSING" in report.blockers


def test_sender_signer_and_live_surfaces_are_forbidden() -> None:
    report = evaluate_runtime_supervision_evidence(
        _bundle(
            active_surface=(
                "sender-module-present",
                "signer-module-present",
                "live-permit-present",
                "trading-wallet-present",
            )
        )
    )

    assert "FORBIDDEN_ACTIVE_SURFACE:sender-module-present" in report.blockers
    assert "FORBIDDEN_ACTIVE_SURFACE:signer-module-present" in report.blockers
    assert "FORBIDDEN_ACTIVE_SURFACE:live-permit-present" in report.blockers
    assert "FORBIDDEN_ACTIVE_SURFACE:trading-wallet-present" in report.blockers


def test_required_supervision_artifacts_must_be_present() -> None:
    report = evaluate_runtime_supervision_evidence(
        _bundle(evidence_artifacts={"runtime_trace_sha256": DIGEST_A})
    )

    assert "SUPERVISION_ARTIFACT_MISSING:shutdown_trace_sha256" in report.blockers
    assert "SUPERVISION_ARTIFACT_MISSING:queue_lifecycle_sha256" in report.blockers


def test_unknown_strategy_state_is_malformed_evidence() -> None:
    with pytest.raises(ValueError, match="strategy.state is unsupported"):
        _strategy(state="zombie")
