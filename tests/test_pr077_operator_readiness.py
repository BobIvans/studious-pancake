from __future__ import annotations

import pytest

from src.operations.operator_readiness import (
    BackupRestoreEvidence,
    LifecycleRecoveryEvidence,
    OperatorReadinessBlocker,
    OperatorReadinessGate,
    StageMetricEvidence,
    TraceStageEvidence,
    build_operator_evidence_from_status,
    sha256_json,
)

pytestmark = pytest.mark.unit
TRACE_ID = "trace-pr077-001"


def _hash(label: str) -> str:
    return sha256_json({"label": label})


def _trace_stages(*, failed_stage: str | None = None) -> tuple[TraceStageEvidence, ...]:
    stages = []
    for index, stage in enumerate(
        ("discovery", "quota", "candidate", "planner", "simulation", "reconciliation")
    ):
        stages.append(
            TraceStageEvidence(
                stage=stage,
                trace_id=TRACE_ID,
                status="failed" if stage == failed_stage else "ok",
                evidence_hash=_hash(f"trace:{stage}"),
                started_at_unix_ns=1_000 + index,
                ended_at_unix_ns=2_000 + index,
            )
        )
    return tuple(stages)


def _metrics() -> tuple[StageMetricEvidence, ...]:
    return tuple(
        StageMetricEvidence(
            stage=stage,
            counters={"events": 1, "retries": 0},
            gauges={"queue_depth": 0},
        )
        for stage in (
            "discovery",
            "quota",
            "candidate",
            "planner",
            "simulation",
            "reconciliation",
        )
    )


def _lifecycle(
    *,
    unsafe_stage: str | None = None,
    duplicate_outcome_stage: str | None = None,
    duplicate_reservation_stage: str | None = None,
) -> tuple[LifecycleRecoveryEvidence, ...]:
    stages = (
        "discovery",
        "capital_reservation",
        "planner",
        "final_simulation",
        "reconciliation",
        "paper_outcome",
    )
    return tuple(
        LifecycleRecoveryEvidence(
            stage=stage,
            recovery_state="recoverable",
            idempotency_key=f"{TRACE_ID}:{stage}",
            evidence_hash=_hash(f"lifecycle:{stage}"),
            replay_safe=stage != unsafe_stage,
            duplicate_outcome=stage == duplicate_outcome_stage,
            duplicate_reservation=stage == duplicate_reservation_stage,
        )
        for stage in stages
    )


def _backup(*, reviewed: bool = True) -> BackupRestoreEvidence:
    digest = _hash("backup-artifact")
    return BackupRestoreEvidence(
        artifact_path="artifacts/pr077/backup-restore.json",
        artifact_sha256=digest,
        restored_sha256=digest,
        migration_checked=True,
        corruption_handled=True,
        reviewed=reviewed,
        reviewer="operator-review",
    )


def _status(*, ready: bool = True, live: bool = False) -> dict[str, object]:
    return {
        "health": {"ok": True},
        "readiness": {"ok": ready},
        "safety": {
            "live_enabled": live,
            "submitted": False,
            "signing_enabled": False,
        },
    }


def _evidence(**overrides: object):
    values = {
        "trace_id": TRACE_ID,
        "status_payload": _status(),
        "data_plane_ready": True,
        "data_plane_reasons": ("PR040_OK",),
        "trace_stages": _trace_stages(),
        "metrics": _metrics(),
        "lifecycle_recovery": _lifecycle(),
        "backup_restore": _backup(),
        "logs_redacted": True,
        "indeterminate_reconciliation": False,
    }
    values.update(overrides)
    return build_operator_evidence_from_status(**values)


def test_pr077_complete_operator_evidence_is_ready_without_live_mutation():
    result = OperatorReadinessGate().evaluate(_evidence())

    assert result.ready is True
    assert result.state == "operator-ready-for-shadow-soak-review"
    assert result.blockers == ()
    assert result.live_mutation_allowed is False
    assert result.evidence_hash != "0" * 64
    assert result.trace_id == TRACE_ID


@pytest.mark.parametrize(
    ("reasons", "expected"),
    [
        (("PR040_RPC_SLOT_DIVERGENCE",), "RPC_STALE_OR_INCONSISTENT"),
        (("PR040_WS_RESUBSCRIBE_REQUIRED",), "WEBSOCKET_GAP_OR_STALE"),
        (("PR040_SLOT_GAP",), "WEBSOCKET_GAP_OR_STALE"),
        (("PR040_ORACLE_CONFIDENCE_TOO_WIDE",), "ORACLE_STALE_OR_LOW_CONFIDENCE"),
    ],
)
def test_readiness_false_on_rpc_gap_or_oracle_dependency(reasons, expected):
    evidence = _evidence(data_plane_ready=False, data_plane_reasons=reasons)
    result = OperatorReadinessGate().evaluate(evidence)

    assert result.ready is False
    assert OperatorReadinessBlocker.DATA_PLANE_NOT_READY.value in result.blockers
    assert expected in result.blockers


def test_readiness_false_on_indeterminate_reconciliation_and_status_not_ready():
    evidence = _evidence(
        status_payload=_status(ready=False),
        indeterminate_reconciliation=True,
    )
    result = OperatorReadinessGate().evaluate(evidence)

    assert result.ready is False
    assert OperatorReadinessBlocker.HTTP_READY_NOT_READY.value in result.blockers
    assert (
        OperatorReadinessBlocker.RECONCILIATION_INDETERMINATE.value
        in result.blockers
    )


def test_restart_recovery_must_cover_every_lifecycle_stage_without_duplicates():
    lifecycle = tuple(
        item
        for item in _lifecycle(
            unsafe_stage="planner",
            duplicate_outcome_stage="reconciliation",
            duplicate_reservation_stage="capital_reservation",
        )
        if item.stage != "paper_outcome"
    )
    evidence = _evidence(lifecycle_recovery=lifecycle)
    result = OperatorReadinessGate().evaluate(evidence)

    assert result.ready is False
    assert OperatorReadinessBlocker.LIFECYCLE_STAGE_MISSING.value in result.blockers
    assert OperatorReadinessBlocker.LIFECYCLE_RECOVERY_UNSAFE.value in result.blockers
    assert OperatorReadinessBlocker.LIFECYCLE_DUPLICATE_OUTCOME.value in result.blockers
    assert (
        OperatorReadinessBlocker.LIFECYCLE_DUPLICATE_RESERVATION.value
        in result.blockers
    )


def test_backup_restore_and_log_redaction_are_required():
    evidence = _evidence(
        backup_restore=_backup(reviewed=False),
        logs_redacted=False,
    )
    result = OperatorReadinessGate().evaluate(evidence)

    assert result.ready is False
    assert OperatorReadinessBlocker.BACKUP_RESTORE_NOT_REVIEWED.value in result.blockers
    assert OperatorReadinessBlocker.LOG_REDACTION_MISSING.value in result.blockers


def test_raw_private_data_or_live_status_blocks_operator_readiness():
    evidence = _evidence(status_payload=_status(live=True))
    result = OperatorReadinessGate().evaluate(evidence)

    assert result.ready is False
    assert OperatorReadinessBlocker.LIVE_MUTATION_PRESENT.value in result.blockers
