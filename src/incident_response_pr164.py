"""PR-164 production alerting, on-call, and incident-response delivery gate.

The module is intentionally side-effect free.  It models the minimum evidence that
must exist before a production-style soak or live canary can rely on alerting.
It does not send notifications, open network connections, or enable live mode.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any

PR164_SCHEMA_VERSION = "pr164.alerting-incident-response.v1"
PR164_RESULT_SCHEMA_VERSION = "pr164.alerting-incident-response-result.v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{2,96}$")
_SAFE_URL_RE = re.compile(r"^https://[A-Za-z0-9][A-Za-z0-9_.:/?&=#%+-]{6,300}$")
_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|token|private[_-]?key|authorization)"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)x-api-key"),
)


class PR164AlertingError(ValueError):
    """Raised when the PR-164 alerting evidence package is malformed."""


class AlertSeverity(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class ReceiverKind(StrEnum):
    ALERTMANAGER = "alertmanager"
    PAGER = "pager"
    SLACK = "slack"
    EMAIL = "email"
    WEBHOOK = "webhook"


class IncidentState(StrEnum):
    DECLARED = "declared"
    TRIAGED = "triaged"
    CONTAINED = "contained"
    RECOVERED = "recovered"
    MONITORED = "monitored"
    CLOSED = "closed"
    POSTMORTEM_REQUIRED = "postmortem-required"


@dataclass(frozen=True, slots=True)
class AlertReceiver:
    """One concrete notification receiver.

    ``production_verified`` means delivery is backed by a reviewed/synthetic test
    artifact.  It is not inferred from a hostname or receiver label.
    """

    receiver_id: str
    kind: ReceiverKind
    endpoint_ref: str
    production_verified: bool
    ack_supported: bool
    secret_free: bool = True

    def __post_init__(self) -> None:
        _require_safe_id(self.receiver_id, "receiver_id")
        _require_safe_id(self.endpoint_ref, "endpoint_ref")
        _require_bool(self.production_verified, "production_verified")
        _require_bool(self.ack_supported, "ack_supported")
        _require_bool(self.secret_free, "secret_free")


@dataclass(frozen=True, slots=True)
class AlertRule:
    """Prometheus/Alertmanager-style alert rule contract."""

    rule_id: str
    severity: AlertSeverity
    component: str
    expression: str
    runbook_url: str
    owner: str
    expected_response_minutes: int
    receiver_ids: tuple[str, ...]
    evidence_ref: str
    safe_payload_example: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_safe_id(self.rule_id, "rule_id")
        _require_safe_id(self.component, "component")
        _require_safe_id(self.owner, "owner")
        _require_safe_id(self.evidence_ref, "evidence_ref")
        if not self.expression.strip():
            raise PR164AlertingError("alert expression is required")
        if not _SAFE_URL_RE.fullmatch(self.runbook_url):
            raise PR164AlertingError("runbook_url must be a safe HTTPS URL")
        if self.expected_response_minutes <= 0:
            raise PR164AlertingError("expected_response_minutes must be positive")
        if not self.receiver_ids:
            raise PR164AlertingError("alert rule must route to at least one receiver")
        for receiver_id in self.receiver_ids:
            _require_safe_id(receiver_id, "receiver_id")
        _assert_no_secret(self.safe_payload_example, f"rule {self.rule_id} payload")


@dataclass(frozen=True, slots=True)
class AlertRoutePolicy:
    """Routing semantics that convert firing alerts into delivered evidence."""

    grouping_enabled: bool
    deduplication_enabled: bool
    inhibition_enabled: bool
    silences_require_review: bool
    resolved_notifications: bool
    p0_p1_min_independent_receivers: int = 2

    def __post_init__(self) -> None:
        for field_name in (
            "grouping_enabled",
            "deduplication_enabled",
            "inhibition_enabled",
            "silences_require_review",
            "resolved_notifications",
        ):
            _require_bool(getattr(self, field_name), field_name)
        if self.p0_p1_min_independent_receivers < 2:
            raise PR164AlertingError(
                "P0/P1 alerts require at least two independent receivers"
            )


@dataclass(frozen=True, slots=True)
class DurableAlertStore:
    """Restart-safe state machine evidence for alert delivery and incidents."""

    supports_firing: bool
    supports_queued: bool
    supports_sent: bool
    supports_delivery_failed: bool
    supports_acknowledged: bool
    supports_escalated: bool
    supports_resolved: bool
    supports_closed: bool
    restart_safe: bool
    dedup_survives_restart: bool
    ack_survives_restart: bool

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            _require_bool(getattr(self, field_name), field_name)

    @property
    def complete(self) -> bool:
        return all(
            getattr(self, field_name) for field_name in self.__dataclass_fields__
        )


@dataclass(frozen=True, slots=True)
class OnCallPolicy:
    """Escalation contract for actionable production alerts."""

    primary: str
    secondary: str
    escalation_manager: str
    timezone: str
    p0_ack_deadline_minutes: int
    p1_ack_deadline_minutes: int
    auto_escalation_enabled: bool
    handoff_required: bool

    def __post_init__(self) -> None:
        for field_name in ("primary", "secondary", "escalation_manager"):
            _require_safe_id(getattr(self, field_name), field_name)
        if len({self.primary, self.secondary, self.escalation_manager}) != 3:
            raise PR164AlertingError("on-call identities must be independent")
        if not self.timezone or "/" not in self.timezone:
            raise PR164AlertingError("timezone must be an IANA-style name")
        if self.p0_ack_deadline_minutes <= 0 or self.p1_ack_deadline_minutes <= 0:
            raise PR164AlertingError("ack deadlines must be positive")
        if self.p0_ack_deadline_minutes > self.p1_ack_deadline_minutes:
            raise PR164AlertingError("P0 acknowledgement must be no slower than P1")
        _require_bool(self.auto_escalation_enabled, "auto_escalation_enabled")
        _require_bool(self.handoff_required, "handoff_required")


@dataclass(frozen=True, slots=True)
class SyntheticAlertDrill:
    """Evidence that the configured alert pipeline actually fires and resolves."""

    drill_id: str
    rules_fired: bool
    alertmanager_received: bool
    all_receivers_delivered: bool
    acknowledgement_tested: bool
    escalation_tested: bool
    resolved_notification_tested: bool
    evidence_sha256: str
    current: bool

    def __post_init__(self) -> None:
        _require_safe_id(self.drill_id, "drill_id")
        object.__setattr__(
            self, "evidence_sha256", _require_sha256(self.evidence_sha256)
        )
        for field_name in (
            "rules_fired",
            "alertmanager_received",
            "all_receivers_delivered",
            "acknowledgement_tested",
            "escalation_tested",
            "resolved_notification_tested",
            "current",
        ):
            _require_bool(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class IncidentLifecyclePolicy:
    """Incident timeline and runbook evidence requirements."""

    supported_states: tuple[IncidentState, ...]
    links_alerts: bool
    links_latches: bool
    links_operator_actions: bool
    links_recovery_commands: bool
    links_evidence: bool
    postmortem_required_for_p0_p1: bool

    def __post_init__(self) -> None:
        required = set(IncidentState)
        if set(self.supported_states) != required:
            raise PR164AlertingError("incident lifecycle must support every state")
        for field_name in (
            "links_alerts",
            "links_latches",
            "links_operator_actions",
            "links_recovery_commands",
            "links_evidence",
            "postmortem_required_for_p0_p1",
        ):
            _require_bool(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class ErrorBudgetPolicy:
    """Promotion latches for exhausted operational SLO budgets."""

    discovery_budget: bool
    paper_readiness_budget: bool
    settlement_budget: bool
    alert_delivery_budget: bool
    backup_restore_budget: bool
    provider_conformance_budget: bool
    promotion_stops_when_exhausted: bool

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            _require_bool(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class PR164AlertingPackage:
    """Complete reviewed alerting/on-call/incident evidence package."""

    receivers: tuple[AlertReceiver, ...]
    rules: tuple[AlertRule, ...]
    routing: AlertRoutePolicy
    durable_store: DurableAlertStore
    on_call: OnCallPolicy
    synthetic_drill: SyntheticAlertDrill
    incident_lifecycle: IncidentLifecyclePolicy
    error_budgets: ErrorBudgetPolicy
    canary_requested: bool = False
    schema_version: str = PR164_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR164_SCHEMA_VERSION:
            raise PR164AlertingError("unsupported PR-164 schema")
        _require_bool(self.canary_requested, "canary_requested")
        receiver_ids = [receiver.receiver_id for receiver in self.receivers]
        rule_ids = [rule.rule_id for rule in self.rules]
        if len(receiver_ids) != len(set(receiver_ids)):
            raise PR164AlertingError("receiver IDs must be unique")
        if len(rule_ids) != len(set(rule_ids)):
            raise PR164AlertingError("rule IDs must be unique")


@dataclass(frozen=True, slots=True)
class PR164Readiness:
    """Fail-closed readiness result for the alerting pipeline."""

    schema_version: str
    production_alerting_ready: bool
    canary_blocked: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    report_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_pr164_alerting(package: PR164AlertingPackage) -> PR164Readiness:
    """Evaluate whether production-style alerting evidence is complete."""

    blockers: list[str] = []
    warnings: list[str] = []
    receivers = {receiver.receiver_id: receiver for receiver in package.receivers}

    _check_receivers(blockers, package.receivers)
    _check_rules(blockers, package.rules, receivers, package.routing)
    _check_routing(blockers, package.routing)
    _check_store(blockers, package.durable_store)
    _check_on_call(blockers, package.on_call)
    _check_synthetic_drill(blockers, package.synthetic_drill)
    _check_incidents(blockers, package.incident_lifecycle)
    _check_error_budgets(blockers, package.error_budgets)

    if not _has_rule_for(package.rules, "runtime-not-ready"):
        blockers.append("MISSING_RUNTIME_NOT_READY_RULE")
    if not _has_rule_for(package.rules, "wallet-reserve-breach"):
        blockers.append("MISSING_WALLET_RESERVE_RULE")
    if not _has_rule_for(package.rules, "ambiguous-submission"):
        blockers.append("MISSING_AMBIGUOUS_SUBMISSION_RULE")
    if not _has_rule_for(package.rules, "backup-failure"):
        blockers.append("MISSING_BACKUP_FAILURE_RULE")
    if not _has_rule_for(package.rules, "security-gate-failure"):
        blockers.append("MISSING_SECURITY_GATE_RULE")

    if package.canary_requested and blockers:
        warnings.append("CANARY_REQUEST_BLOCKED_BY_UNHEALTHY_ALERTING")

    report_payload = {
        "schema_version": PR164_RESULT_SCHEMA_VERSION,
        "production_alerting_ready": not blockers,
        "canary_blocked": bool(blockers),
        "blockers": sorted(blockers),
        "warnings": tuple(warnings),
        "package_hash": _sha256_payload(package),
    }
    return PR164Readiness(
        schema_version=PR164_RESULT_SCHEMA_VERSION,
        production_alerting_ready=not blockers,
        canary_blocked=bool(blockers),
        blockers=tuple(sorted(blockers)),
        warnings=tuple(warnings),
        report_sha256=_sha256_payload(report_payload),
    )


def _check_receivers(blockers: list[str], receivers: tuple[AlertReceiver, ...]) -> None:
    if not receivers:
        blockers.append("NO_ALERT_RECEIVERS")
        blockers.append("NO_PRODUCTION_VERIFIED_RECEIVER")
        return
    verified = [receiver for receiver in receivers if receiver.production_verified]
    if not verified:
        blockers.append("NO_PRODUCTION_VERIFIED_RECEIVER")
    if any(not receiver.secret_free for receiver in receivers):
        blockers.append("RECEIVER_CONTAINS_SECRET_MATERIAL")


def _check_rules(
    blockers: list[str],
    rules: tuple[AlertRule, ...],
    receivers: dict[str, AlertReceiver],
    routing: AlertRoutePolicy,
) -> None:
    if not rules:
        blockers.append("NO_ALERT_RULES")
        return

    for rule in rules:
        missing = [
            receiver_id
            for receiver_id in rule.receiver_ids
            if receiver_id not in receivers
        ]
        if missing:
            blockers.append(f"RULE_{rule.rule_id}_UNKNOWN_RECEIVER")
            continue
        routed = [receivers[receiver_id] for receiver_id in rule.receiver_ids]
        verified = [receiver for receiver in routed if receiver.production_verified]
        if not verified:
            blockers.append(f"RULE_{rule.rule_id}_NO_VERIFIED_DELIVERY")
        if rule.severity in {AlertSeverity.P0, AlertSeverity.P1}:
            if len({receiver.receiver_id for receiver in verified}) < (
                routing.p0_p1_min_independent_receivers
            ):
                blockers.append(f"RULE_{rule.rule_id}_NEEDS_REDUNDANT_DELIVERY")
            if not all(receiver.ack_supported for receiver in verified):
                blockers.append(f"RULE_{rule.rule_id}_ACK_NOT_SUPPORTED")
        _assert_no_secret(rule.safe_payload_example, f"rule {rule.rule_id} payload")


def _check_routing(blockers: list[str], routing: AlertRoutePolicy) -> None:
    required = {
        "ROUTING_GROUPING_MISSING": routing.grouping_enabled,
        "ROUTING_DEDUP_MISSING": routing.deduplication_enabled,
        "ROUTING_INHIBITION_MISSING": routing.inhibition_enabled,
        "ROUTING_SILENCE_REVIEW_MISSING": routing.silences_require_review,
        "ROUTING_RESOLVED_NOTIFICATIONS_MISSING": routing.resolved_notifications,
    }
    blockers.extend(code for code, passed in required.items() if not passed)


def _check_store(blockers: list[str], store: DurableAlertStore) -> None:
    if not store.complete:
        blockers.append("DURABLE_ALERT_STATE_INCOMPLETE")


def _check_on_call(blockers: list[str], on_call: OnCallPolicy) -> None:
    if not on_call.auto_escalation_enabled:
        blockers.append("P0_AUTO_ESCALATION_MISSING")
    if not on_call.handoff_required:
        blockers.append("ONCALL_HANDOFF_MISSING")


def _check_synthetic_drill(blockers: list[str], drill: SyntheticAlertDrill) -> None:
    required = {
        "SYNTHETIC_RULE_FIRE_MISSING": drill.rules_fired,
        "SYNTHETIC_ALERTMANAGER_RECEIPT_MISSING": drill.alertmanager_received,
        "SYNTHETIC_RECEIVER_DELIVERY_MISSING": drill.all_receivers_delivered,
        "SYNTHETIC_ACK_MISSING": drill.acknowledgement_tested,
        "SYNTHETIC_ESCALATION_MISSING": drill.escalation_tested,
        "SYNTHETIC_RESOLVED_NOTIFICATION_MISSING": drill.resolved_notification_tested,
        "SYNTHETIC_DRILL_STALE": drill.current,
    }
    blockers.extend(code for code, passed in required.items() if not passed)


def _check_incidents(blockers: list[str], lifecycle: IncidentLifecyclePolicy) -> None:
    required = {
        "INCIDENT_ALERT_LINK_MISSING": lifecycle.links_alerts,
        "INCIDENT_LATCH_LINK_MISSING": lifecycle.links_latches,
        "INCIDENT_OPERATOR_ACTION_LINK_MISSING": lifecycle.links_operator_actions,
        "INCIDENT_RECOVERY_COMMAND_LINK_MISSING": lifecycle.links_recovery_commands,
        "INCIDENT_EVIDENCE_LINK_MISSING": lifecycle.links_evidence,
        "INCIDENT_POSTMORTEM_POLICY_MISSING": lifecycle.postmortem_required_for_p0_p1,
    }
    blockers.extend(code for code, passed in required.items() if not passed)


def _check_error_budgets(blockers: list[str], budgets: ErrorBudgetPolicy) -> None:
    required = {
        "DISCOVERY_ERROR_BUDGET_MISSING": budgets.discovery_budget,
        "PAPER_READINESS_ERROR_BUDGET_MISSING": budgets.paper_readiness_budget,
        "SETTLEMENT_ERROR_BUDGET_MISSING": budgets.settlement_budget,
        "ALERT_DELIVERY_ERROR_BUDGET_MISSING": budgets.alert_delivery_budget,
        "BACKUP_RESTORE_ERROR_BUDGET_MISSING": budgets.backup_restore_budget,
        (
            "PROVIDER_CONFORMANCE_ERROR_BUDGET_MISSING"
        ): budgets.provider_conformance_budget,
        "PROMOTION_ERROR_BUDGET_LATCH_MISSING": budgets.promotion_stops_when_exhausted,
    }
    blockers.extend(code for code, passed in required.items() if not passed)


def _has_rule_for(rules: tuple[AlertRule, ...], component: str) -> bool:
    return any(rule.component == component for rule in rules)


def _require_bool(value: bool, name: str) -> None:
    if not isinstance(value, bool):
        raise PR164AlertingError(f"{name} must be bool")


def _require_safe_id(value: str, name: str) -> str:
    if not _SAFE_ID_RE.fullmatch(value):
        raise PR164AlertingError(f"{name} must be a stable safe identifier")
    return value


def _require_sha256(value: str) -> str:
    lowered = value.lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise PR164AlertingError("expected non-placeholder sha256")
    return lowered


def _assert_no_secret(value: Any, context: str) -> None:
    text = json.dumps(_jsonable(value), sort_keys=True, default=str)
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            raise PR164AlertingError(f"{context} contains secret-looking material")


def _sha256_payload(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _jsonable(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return str(value)
    if is_dataclass(value):
        return {key: _jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(val) for key, val in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def group_rules_by_severity(rules: tuple[AlertRule, ...]) -> dict[str, list[str]]:
    """Return a deterministic rule inventory for docs/tests."""

    grouped: dict[str, list[str]] = defaultdict(list)
    for rule in rules:
        grouped[str(rule.severity)].append(rule.rule_id)
    return {severity: sorted(ids) for severity, ids in sorted(grouped.items())}
