"""PR-042 readiness adapter for PR-046 canary reports."""

from __future__ import annotations

from src.observability.health import DependencyState, DependencyStatus

from .models import CanaryMode, CanaryReport


def canary_dependency_status(
    report: CanaryReport, *, updated_at_unix_ns: int
) -> DependencyStatus:
    """Convert a redaction-safe canary report into one critical readiness row."""

    if report.active_latches:
        state = DependencyState.UNAVAILABLE
        reason = "limited-live safety latch active"
    elif report.mode is CanaryMode.SHADOW or not report.armed:
        state = DependencyState.DISABLED
        reason = "limited-live canary is not armed"
    elif report.outstanding_attempt_id is not None:
        state = DependencyState.DEGRADED
        reason = "one canary submission is awaiting mandatory reconciliation"
    else:
        state = DependencyState.OK
        reason = "limited-live canary admission is armed and idle"

    return DependencyStatus(
        name="limited_live_canary",
        kind="execution_safety",
        state=state,
        critical=True,
        reason=reason,
        updated_at_unix_ns=updated_at_unix_ns,
        labels={
            "policy_hash": report.policy_hash,
            "report_hash": report.report_hash,
            "latch_count": str(len(report.active_latches)),
            "ai_authority": "false",
        },
    )
