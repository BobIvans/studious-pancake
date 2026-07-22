# fmt: off
from __future__ import annotations

from copy import deepcopy

from src.operator_ack_pr143 import (
    PR143Decision,
    evaluate_operator_acknowledgement,
    main,
)


_NOW = "2026-07-22T12:00:00Z"


def test_drift_pin_rotation_acknowledgement_enters_manual_review() -> None:
    result = evaluate_operator_acknowledgement(_payload(), current_utc=_NOW)

    assert result.decision is PR143Decision.MANUAL_REVIEW
    assert result.execution_capability_allowed is False
    assert result.canary_release_allowed is False
    assert result.operator_alert is True
    assert result.blockers == ()
    assert "PR143_OPERATOR_ALERT_REQUIRED" in result.warnings
    assert result.acknowledgement_fingerprint is not None


def test_auto_approval_is_forbidden() -> None:
    payload = _payload()
    acknowledgement = payload["acknowledgement"]
    assert isinstance(acknowledgement, dict)
    acknowledgement["auto_approved"] = True

    result = evaluate_operator_acknowledgement(payload, current_utc=_NOW)

    assert result.decision is PR143Decision.BLOCKED
    assert "PR143_AUTO_APPROVAL_FORBIDDEN" in result.blockers
    assert result.acknowledgement_fingerprint is None


def test_stale_acknowledgement_blocks() -> None:
    payload = _payload()
    acknowledgement = payload["acknowledgement"]
    assert isinstance(acknowledgement, dict)
    acknowledgement["acknowledged_at_utc"] = "2026-07-20T00:00:00Z"

    result = evaluate_operator_acknowledgement(payload, current_utc=_NOW)

    assert result.decision is PR143Decision.BLOCKED
    assert "PR143_ACKNOWLEDGEMENT_STALE" in result.blockers


def test_required_statements_are_enforced() -> None:
    payload = _payload()
    acknowledgement = payload["acknowledgement"]
    assert isinstance(acknowledgement, dict)
    acknowledgement["statements"] = ["reviewed-evidence-bundle"]

    result = evaluate_operator_acknowledgement(payload, current_utc=_NOW)

    assert result.decision is PR143Decision.BLOCKED
    assert (
        "PR143_REQUIRED_STATEMENT_MISSING:understands-no-auto-acceptance"
        in result.blockers
    )


def test_live_canary_requires_second_human_reviewer() -> None:
    payload = _payload(intent="live-canary")
    payload["unresolved_drift_events"] = []
    payload["pin_rotation_pr_required"] = False
    payload["secondary_reviewer_id"] = None

    result = evaluate_operator_acknowledgement(payload, current_utc=_NOW)

    assert result.decision is PR143Decision.BLOCKED
    assert "PR143_SECOND_REVIEWER_REQUIRED" in result.blockers


def test_unresolved_drift_blocks_release_promotion() -> None:
    payload = _payload(intent="release-promotion")

    result = evaluate_operator_acknowledgement(payload, current_utc=_NOW)

    assert result.decision is PR143Decision.BLOCKED
    assert "PR143_UNRESOLVED_DRIFT_BLOCKS_RELEASE" in result.blockers


def test_redaction_makes_secret_changes_fingerprint_stable() -> None:
    payload_a = _payload()
    payload_b = deepcopy(payload_a)
    payload_a["auth_header"] = "Bearer first-secret"
    payload_b["auth_header"] = "Bearer second-secret"

    first = evaluate_operator_acknowledgement(payload_a, current_utc=_NOW)
    second = evaluate_operator_acknowledgement(payload_b, current_utc=_NOW)

    assert first.acknowledgement_fingerprint == second.acknowledgement_fingerprint


def test_cli_self_check_prints_json(capsys) -> None:
    assert main(["--json"]) == 0
    captured = capsys.readouterr()

    assert '"decision": "manual-review"' in captured.out
    assert '"execution_capability_allowed": false' in captured.out


def _payload(*, intent: str = "drift-pin-rotation") -> dict[str, object]:
    return {
        "schema_version": "pr143.operator-acknowledgement-gate.v1",
        "intent": intent,
        "request_id": "1" * 64,
        "evidence_bundle_hash": "2" * 64,
        "policy_hash": "3" * 64,
        "decision_hash": "4" * 64,
        "drift_timeline_hash": "5" * 64,
        "evidence_refs": [
            "workflow-run:scheduled-drift-daily",
            "artifact:drift-evidence.json",
        ],
        "accepts_new_schema_or_code_hash": False,
        "live_submission_hard_disabled": True,
        "pin_rotation_pr_required": True,
        "unresolved_drift_events": ["provider-schema-drift"],
        "acknowledgement": {
            "operator_id": "human:alice",
            "operator_role": "security-reviewer",
            "acknowledged_at_utc": "2026-07-22T11:00:00Z",
            "protected_environment": True,
            "auto_approved": False,
            "statements": [
                "reviewed-evidence-bundle",
                "understands-no-auto-acceptance",
                "confirms-live-submission-remains-disabled",
                "accepts-operator-accountability",
            ],
            "operator_signature": "fixture-only",
        },
    }
# fmt: on
