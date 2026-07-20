from src.live_canary import CanaryPolicy, LimitedLiveCanaryController, OperatorIdentity
from src.live_canary.observability import canary_dependency_status
from src.observability.health import DependencyState


def test_default_canary_is_disabled_in_pr042_readiness() -> None:
    report = LimitedLiveCanaryController(CanaryPolicy()).report()
    dependency = canary_dependency_status(report, updated_at_unix_ns=1)

    assert dependency.state is DependencyState.DISABLED
    assert dependency.critical is True
    assert dependency.labels["ai_authority"] == "false"
    assert dependency.labels["report_hash"] == report.report_hash


def test_latched_canary_is_unavailable() -> None:
    controller = LimitedLiveCanaryController(CanaryPolicy())
    controller.manual_kill(
        operator=OperatorIdentity("operator-alice"),
        reason="manual stop",
        observed_at_ms=1,
    )
    dependency = canary_dependency_status(controller.report(), updated_at_unix_ns=2)

    assert dependency.state is DependencyState.UNAVAILABLE
    assert dependency.reason == "limited-live safety latch active"
