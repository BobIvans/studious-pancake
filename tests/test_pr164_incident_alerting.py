from __future__ import annotations

import pytest

from src.incident_response_pr164 import (
    AlertReceiver,
    AlertRoutePolicy,
    AlertRule,
    AlertSeverity,
    DurableAlertStore,
    ErrorBudgetPolicy,
    IncidentLifecyclePolicy,
    IncidentState,
    OnCallPolicy,
    PR164AlertingError,
    PR164AlertingPackage,
    ReceiverKind,
    SyntheticAlertDrill,
    evaluate_pr164_alerting,
    group_rules_by_severity,
)

GOOD_HASH = "1" * 64


def receiver(receiver_id: str, kind: ReceiverKind) -> AlertReceiver:
    return AlertReceiver(
        receiver_id=receiver_id,
        kind=kind,
        endpoint_ref=f"{receiver_id}:primary",
        production_verified=True,
        ack_supported=True,
    )


def rule(
    rule_id: str,
    component: str,
    severity: AlertSeverity = AlertSeverity.P0,
    receivers: tuple[str, ...] = ("pagerduty:p0", "slack:p0"),
) -> AlertRule:
    return AlertRule(
        rule_id=rule_id,
        severity=severity,
        component=component,
        expression=f"{component}_unhealthy > 0",
        runbook_url=f"https://runbooks.example.com/{rule_id}",
        owner="sre-primary",
        expected_response_minutes=5,
        receiver_ids=receivers,
        evidence_ref=f"{rule_id}:evidence",
        safe_payload_example={
            "alert_id": rule_id,
            "component": component,
            "attempt_id": "attempt-redacted",
        },
    )


def package(**overrides: object) -> PR164AlertingPackage:
    receivers = (
        receiver("pagerduty:p0", ReceiverKind.PAGER),
        receiver("slack:p0", ReceiverKind.SLACK),
        receiver("email:p2", ReceiverKind.EMAIL),
    )
    rules = (
        rule("runtime-not-ready-p0", "runtime-not-ready"),
        rule("wallet-reserve-breach-p0", "wallet-reserve-breach"),
        rule("ambiguous-submission-p0", "ambiguous-submission"),
        rule("backup-failure-p2", "backup-failure", AlertSeverity.P2, ("email:p2",)),
        rule("security-gate-failure-p1", "security-gate-failure", AlertSeverity.P1),
    )
    values = {
        "receivers": receivers,
        "rules": rules,
        "routing": AlertRoutePolicy(
            grouping_enabled=True,
            deduplication_enabled=True,
            inhibition_enabled=True,
            silences_require_review=True,
            resolved_notifications=True,
        ),
        "durable_store": DurableAlertStore(
            supports_firing=True,
            supports_queued=True,
            supports_sent=True,
            supports_delivery_failed=True,
            supports_acknowledged=True,
            supports_escalated=True,
            supports_resolved=True,
            supports_closed=True,
            restart_safe=True,
            dedup_survives_restart=True,
            ack_survives_restart=True,
        ),
        "on_call": OnCallPolicy(
            primary="alice-sre",
            secondary="bob-sre",
            escalation_manager="carol-manager",
            timezone="Europe/Riga",
            p0_ack_deadline_minutes=5,
            p1_ack_deadline_minutes=15,
            auto_escalation_enabled=True,
            handoff_required=True,
        ),
        "synthetic_drill": SyntheticAlertDrill(
            drill_id="synthetic-alert-e2e",
            rules_fired=True,
            alertmanager_received=True,
            all_receivers_delivered=True,
            acknowledgement_tested=True,
            escalation_tested=True,
            resolved_notification_tested=True,
            evidence_sha256=GOOD_HASH,
            current=True,
        ),
        "incident_lifecycle": IncidentLifecyclePolicy(
            supported_states=tuple(IncidentState),
            links_alerts=True,
            links_latches=True,
            links_operator_actions=True,
            links_recovery_commands=True,
            links_evidence=True,
            postmortem_required_for_p0_p1=True,
        ),
        "error_budgets": ErrorBudgetPolicy(
            discovery_budget=True,
            paper_readiness_budget=True,
            settlement_budget=True,
            alert_delivery_budget=True,
            backup_restore_budget=True,
            provider_conformance_budget=True,
            promotion_stops_when_exhausted=True,
        ),
    }
    values.update(overrides)
    return PR164AlertingPackage(**values)


def test_complete_alerting_package_is_ready_but_does_not_send_anything() -> None:
    result = evaluate_pr164_alerting(package())

    assert result.production_alerting_ready is True
    assert result.canary_blocked is False
    assert result.blockers == ()
    assert len(result.report_sha256) == 64


def test_operator_alert_boolean_without_delivery_state_blocks() -> None:
    result = evaluate_pr164_alerting(package(receivers=()))

    assert result.production_alerting_ready is False
    assert "NO_ALERT_RECEIVERS" in result.blockers
    assert "NO_PRODUCTION_VERIFIED_RECEIVER" in result.blockers


def test_p0_p1_alerts_require_two_verified_ackable_channels() -> None:
    result = evaluate_pr164_alerting(
        package(
            rules=(
                rule(
                    "ambiguous-submission-p0",
                    "ambiguous-submission",
                    receivers=("pagerduty:p0",),
                ),
                rule("runtime-not-ready-p0", "runtime-not-ready"),
                rule("wallet-reserve-breach-p0", "wallet-reserve-breach"),
                rule(
                    "backup-failure-p2",
                    "backup-failure",
                    AlertSeverity.P2,
                    ("email:p2",),
                ),
                rule("security-gate-failure-p1", "security-gate-failure"),
            )
        )
    )

    assert "RULE_ambiguous-submission-p0_NEEDS_REDUNDANT_DELIVERY" in result.blockers


def test_grouping_dedup_inhibition_silence_review_are_required() -> None:
    result = evaluate_pr164_alerting(
        package(
            routing=AlertRoutePolicy(
                grouping_enabled=False,
                deduplication_enabled=False,
                inhibition_enabled=False,
                silences_require_review=False,
                resolved_notifications=False,
            )
        )
    )

    assert "ROUTING_GROUPING_MISSING" in result.blockers
    assert "ROUTING_DEDUP_MISSING" in result.blockers
    assert "ROUTING_INHIBITION_MISSING" in result.blockers
    assert "ROUTING_SILENCE_REVIEW_MISSING" in result.blockers
    assert "ROUTING_RESOLVED_NOTIFICATIONS_MISSING" in result.blockers


def test_durable_delivery_states_must_survive_restart() -> None:
    broken_store = DurableAlertStore(
        supports_firing=True,
        supports_queued=True,
        supports_sent=True,
        supports_delivery_failed=False,
        supports_acknowledged=True,
        supports_escalated=True,
        supports_resolved=True,
        supports_closed=True,
        restart_safe=False,
        dedup_survives_restart=True,
        ack_survives_restart=True,
    )
    result = evaluate_pr164_alerting(package(durable_store=broken_store))

    assert "DURABLE_ALERT_STATE_INCOMPLETE" in result.blockers


def test_synthetic_alert_drill_must_cover_ack_escalation_and_resolve() -> None:
    result = evaluate_pr164_alerting(
        package(
            synthetic_drill=SyntheticAlertDrill(
                drill_id="synthetic-alert-e2e",
                rules_fired=True,
                alertmanager_received=True,
                all_receivers_delivered=True,
                acknowledgement_tested=False,
                escalation_tested=False,
                resolved_notification_tested=False,
                evidence_sha256=GOOD_HASH,
                current=True,
            )
        )
    )

    assert "SYNTHETIC_ACK_MISSING" in result.blockers
    assert "SYNTHETIC_ESCALATION_MISSING" in result.blockers
    assert "SYNTHETIC_RESOLVED_NOTIFICATION_MISSING" in result.blockers


def test_alert_payload_rejects_secret_like_material() -> None:
    with pytest.raises(PR164AlertingError, match="secret-looking"):
        AlertRule(
            rule_id="leaky-alert",
            severity=AlertSeverity.P0,
            component="runtime-not-ready",
            expression="up == 0",
            runbook_url="https://runbooks.example.com/leaky-alert",
            owner="sre-primary",
            expected_response_minutes=5,
            receiver_ids=("pagerduty:p0", "slack:p0"),
            evidence_ref="leaky-alert:evidence",
            safe_payload_example={"Authorization": "Bearer secret-token-value"},
        )


def test_incident_lifecycle_requires_links_and_postmortem_policy() -> None:
    lifecycle = IncidentLifecyclePolicy(
        supported_states=tuple(IncidentState),
        links_alerts=True,
        links_latches=False,
        links_operator_actions=False,
        links_recovery_commands=True,
        links_evidence=True,
        postmortem_required_for_p0_p1=False,
    )
    result = evaluate_pr164_alerting(package(incident_lifecycle=lifecycle))

    assert "INCIDENT_LATCH_LINK_MISSING" in result.blockers
    assert "INCIDENT_OPERATOR_ACTION_LINK_MISSING" in result.blockers
    assert "INCIDENT_POSTMORTEM_POLICY_MISSING" in result.blockers


def test_canary_request_is_blocked_when_alert_pipeline_is_unhealthy() -> None:
    result = evaluate_pr164_alerting(package(receivers=(), canary_requested=True))

    assert result.canary_blocked is True
    assert "CANARY_REQUEST_BLOCKED_BY_UNHEALTHY_ALERTING" in result.warnings


def test_required_fund_and_security_rules_are_explicit() -> None:
    result = evaluate_pr164_alerting(
        package(rules=(rule("runtime-not-ready-p0", "runtime-not-ready"),))
    )

    assert "MISSING_WALLET_RESERVE_RULE" in result.blockers
    assert "MISSING_AMBIGUOUS_SUBMISSION_RULE" in result.blockers
    assert "MISSING_BACKUP_FAILURE_RULE" in result.blockers
    assert "MISSING_SECURITY_GATE_RULE" in result.blockers


def test_report_hash_is_deterministic_and_inventory_groups_by_severity() -> None:
    first = evaluate_pr164_alerting(package())
    second = evaluate_pr164_alerting(package())

    assert first.report_sha256 == second.report_sha256
    assert group_rules_by_severity(package().rules)["P0"] == [
        "ambiguous-submission-p0",
        "runtime-not-ready-p0",
        "wallet-reserve-breach-p0",
    ]
