# fmt: off
"""PR-143 offline human acknowledgement gate.

No network calls, no signer/sender integration, and no live-trading enablement.
This guard records when drift or release evidence needs an accountable human
acknowledgement before any later promotion workflow can continue.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import re

PR143_SCHEMA_VERSION = "pr143.operator-acknowledgement-gate.v1"
PR143_RESULT_SCHEMA_VERSION = "pr143.operator-acknowledgement-result.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_STATEMENTS = frozenset({
    "reviewed-evidence-bundle",
    "understands-no-auto-acceptance",
    "confirms-live-submission-remains-disabled",
    "accepts-operator-accountability",
})
_ALLOWED_INTENTS = frozenset({
    "drift-pin-rotation",
    "release-promotion",
    "live-canary",
    "manual-override",
})
_ESCALATED_INTENTS = frozenset({"live-canary", "manual-override"})
_ALLOWED_ROLES = frozenset({"maintainer", "security-reviewer", "release-manager"})


class PR143AcknowledgementError(ValueError):
    """Raised when acknowledgement input shape is invalid."""


class PR143Decision(StrEnum):
    ACKNOWLEDGED = "acknowledged"
    BLOCKED = "blocked"
    MANUAL_REVIEW = "manual-review"


@dataclass(frozen=True, slots=True)
class PR143AcknowledgementResult:
    schema_version: str
    intent: str
    decision: PR143Decision
    execution_capability_allowed: bool
    canary_release_allowed: bool
    operator_alert: bool
    acknowledgement_fingerprint: str | None
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["decision"] = self.decision.value
        return payload


def evaluate_operator_acknowledgement(
    request: Mapping[str, object], *, current_utc: str
) -> PR143AcknowledgementResult:
    """Evaluate a deterministic PR-143 operator acknowledgement package."""

    blockers: list[str] = []
    warnings: list[str] = []
    ack = _mapping(request.get("acknowledgement"), "acknowledgement")
    intent = _string(request, "intent")

    if _string(request, "schema_version") != PR143_SCHEMA_VERSION:
        blockers.append("PR143_SCHEMA_UNSUPPORTED")
    if intent not in _ALLOWED_INTENTS:
        blockers.append("PR143_INTENT_UNSUPPORTED")
    if _string(ack, "operator_role") not in _ALLOWED_ROLES:
        blockers.append("PR143_OPERATOR_ROLE_UNSUPPORTED")
    if _string(ack, "operator_id").lower().startswith(("bot:", "ci:", "automation:")):
        blockers.append("PR143_OPERATOR_MUST_BE_HUMAN")
    if not _boolean(ack, "protected_environment"):
        blockers.append("PR143_PROTECTED_ENVIRONMENT_REQUIRED")
    if _boolean(ack, "auto_approved", default=False):
        blockers.append("PR143_AUTO_APPROVAL_FORBIDDEN")
    if _age_hours(_string(ack, "acknowledged_at_utc"), current_utc) > 24:
        blockers.append("PR143_ACKNOWLEDGEMENT_STALE")

    for field in ("request_id", "evidence_bundle_hash", "policy_hash", "decision_hash"):
        if not _valid_sha(_string(request, field)):
            blockers.append(f"PR143_{field.upper()}_INVALID")
    if len(_sequence(request, "evidence_refs", default=())) < 2:
        blockers.append("PR143_EVIDENCE_REFS_INSUFFICIENT")
    if _boolean(request, "accepts_new_schema_or_code_hash", default=False):
        blockers.append("PR143_NEW_HASH_AUTO_ACCEPTANCE_FORBIDDEN")
    if not _boolean(request, "live_submission_hard_disabled", default=False):
        blockers.append("PR143_LIVE_SUBMISSION_HARD_DISABLE_REQUIRED")
    if not _valid_sha(_optional_string(request, "drift_timeline_hash")):
        warnings.append("PR143_DRIFT_TIMELINE_HASH_MISSING")

    present = {x for x in _sequence(ack, "statements", default=()) if isinstance(x, str)}
    for statement in sorted(_REQUIRED_STATEMENTS - present):
        blockers.append(f"PR143_REQUIRED_STATEMENT_MISSING:{statement}")

    secondary = _optional_string(request, "secondary_reviewer_id")
    if intent in _ESCALATED_INTENTS and not secondary:
        blockers.append("PR143_SECOND_REVIEWER_REQUIRED")
    if secondary and secondary == _string(ack, "operator_id"):
        blockers.append("PR143_SECOND_REVIEWER_MUST_DIFFER")

    unresolved = _sequence(request, "unresolved_drift_events", default=())
    pin_pr = _boolean(request, "pin_rotation_pr_required", default=False)
    if unresolved and intent != "drift-pin-rotation":
        blockers.append("PR143_UNRESOLVED_DRIFT_BLOCKS_RELEASE")
    if (unresolved or intent == "drift-pin-rotation") and not pin_pr:
        blockers.append("PR143_PIN_ROTATION_PR_REQUIRED")
    if unresolved:
        warnings.append("PR143_OPERATOR_ALERT_REQUIRED")

    unique_blockers = tuple(dict.fromkeys(blockers))
    unique_warnings = tuple(dict.fromkeys(warnings))
    decision = _decision(unique_blockers, unique_warnings)
    return PR143AcknowledgementResult(
        PR143_RESULT_SCHEMA_VERSION,
        intent,
        decision,
        False,
        False,
        bool(unique_blockers or unique_warnings),
        None if unique_blockers else acknowledgement_fingerprint(request),
        unique_blockers,
        unique_warnings,
    )


def acknowledgement_fingerprint(payload: Mapping[str, object]) -> str:
    redacted = _redact(payload)
    raw = json.dumps(redacted, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _decision(blockers: Sequence[str], warnings: Sequence[str]) -> PR143Decision:
    if blockers:
        return PR143Decision.BLOCKED
    return PR143Decision.MANUAL_REVIEW if warnings else PR143Decision.ACKNOWLEDGED


def _redact(value: object) -> object:
    if isinstance(value, Mapping):
        out: dict[str, object] = {}
        for key, child in value.items():
            label = str(key)
            if any(token in label.lower() for token in ("auth", "secret", "token")):
                out[label] = "<redacted>"
            elif label in {"freeform_note", "operator_signature"}:
                out[label] = "<redacted>"
            else:
                out[label] = _redact(child)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def _age_hours(start_utc: str, end_utc: str) -> int:
    start = _parse_utc(start_utc)
    end = _parse_utc(end_utc)
    return max(0, int((end - start).total_seconds() // 3600))


def _parse_utc(value: str) -> datetime:
    if not value.endswith("Z"):
        raise PR143AcknowledgementError("FIELD_NOT_UTC_SECOND:utc")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise PR143AcknowledgementError(f"FIELD_NOT_OBJECT:{field}")
    return value


def _string(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise PR143AcknowledgementError(f"FIELD_NOT_STRING:{field}")
    return value


def _optional_string(payload: Mapping[str, object], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise PR143AcknowledgementError(f"FIELD_NOT_STRING:{field}")
    return value


def _sequence(
    payload: Mapping[str, object], field: str, *, default: Sequence[object] | None = None
) -> Sequence[object]:
    value = payload.get(field, default)
    if not isinstance(value, (list, tuple)):
        raise PR143AcknowledgementError(f"FIELD_NOT_LIST:{field}")
    return value


def _boolean(
    payload: Mapping[str, object], field: str, *, default: bool | None = None
) -> bool:
    value = payload.get(field, default)
    if not isinstance(value, bool):
        raise PR143AcknowledgementError(f"FIELD_NOT_BOOL:{field}")
    return value


def _valid_sha(value: str | None) -> bool:
    return isinstance(value, str) and bool(_SHA_RE.fullmatch(value)) and value != "0" * 64


def _self_check_payload() -> dict[str, object]:
    return {
        "schema_version": PR143_SCHEMA_VERSION,
        "intent": "drift-pin-rotation",
        "request_id": "1" * 64,
        "evidence_bundle_hash": "2" * 64,
        "policy_hash": "3" * 64,
        "decision_hash": "4" * 64,
        "drift_timeline_hash": "5" * 64,
        "evidence_refs": ["workflow-run:scheduled-drift", "artifact:drift-evidence"],
        "accepts_new_schema_or_code_hash": False,
        "live_submission_hard_disabled": True,
        "pin_rotation_pr_required": True,
        "unresolved_drift_events": ["provider-schema-drift"],
        "acknowledgement": {
            "operator_id": "human:alice",
            "operator_role": "security-reviewer",
            "acknowledged_at_utc": "2026-07-22T00:00:00Z",
            "protected_environment": True,
            "auto_approved": False,
            "statements": sorted(_REQUIRED_STATEMENTS),
            "operator_signature": "fixture-only",
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate PR-143 acknowledgement evidence.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = evaluate_operator_acknowledgement(
        _self_check_payload(), current_utc="2026-07-22T01:00:00Z"
    )
    output = json.dumps(result.to_dict(), indent=2, sort_keys=True)
    print(output if args.json else result.decision.value)
    return 0 if result.decision is not PR143Decision.BLOCKED else 1


if __name__ == "__main__":
    raise SystemExit(main())
# fmt: on
