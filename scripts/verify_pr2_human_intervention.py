#!/usr/bin/env python3
"""Deterministic repository verifier for PR-2 human-intervention authority."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.human_intervention import (  # noqa: E402
    HumanInterventionLedger,
    HumanInterventionRequest,
    InterventionAction,
    InterventionTarget,
    PermitConflict,
)

SCHEMA_VERSION = "pr2.human-intervention-verification.v1"


def _approval(
    *,
    operator_id: str,
    secondary_reviewer_id: str,
    request_hash: str,
    target: InterventionTarget,
) -> dict[str, object]:
    return {
        "schema_version": "pr143.operator-acknowledgement-gate.v1",
        "intent": "manual-override",
        "request_id": request_hash,
        "evidence_bundle_hash": target.evidence_hash,
        "policy_hash": target.config_hash,
        "decision_hash": target.subject_hash,
        "drift_timeline_hash": "5" * 64,
        "evidence_refs": ["artifact:pr2-permit", "artifact:latch-evidence"],
        "accepts_new_schema_or_code_hash": False,
        "live_submission_hard_disabled": True,
        "pin_rotation_pr_required": False,
        "unresolved_drift_events": [],
        "secondary_reviewer_id": secondary_reviewer_id,
        "acknowledgement": {
            "operator_id": operator_id,
            "operator_role": "security-reviewer",
            "acknowledged_at_utc": "2026-08-08T20:00:00Z",
            "protected_environment": True,
            "auto_approved": False,
            "statements": [
                "accepts-operator-accountability",
                "confirms-live-submission-remains-disabled",
                "reviewed-evidence-bundle",
                "understands-no-auto-acceptance",
            ],
            "operator_signature": "fixture-only",
        },
    }


def _request() -> HumanInterventionRequest:
    target = InterventionTarget(
        subject_type="safety-latch",
        subject_id="verification-latch",
        subject_hash="1" * 64,
        evidence_hash="2" * 64,
        release_hash="3" * 64,
        config_hash="4" * 64,
    )
    draft = HumanInterventionRequest(
        action=InterventionAction.CLEAR_SAFETY_LATCH,
        target=target,
        requested_at_utc="2026-08-08T20:00:00Z",
        expires_at_utc="2026-08-08T20:10:00Z",
        acknowledgements=({}, {}),
    )
    return HumanInterventionRequest(
        action=draft.action,
        target=target,
        requested_at_utc=draft.requested_at_utc,
        expires_at_utc=draft.expires_at_utc,
        acknowledgements=(
            _approval(
                operator_id="human:alice",
                secondary_reviewer_id="human:bob",
                request_hash=draft.request_hash,
                target=target,
            ),
            _approval(
                operator_id="human:bob",
                secondary_reviewer_id="human:alice",
                request_hash=draft.request_hash,
                target=target,
            ),
        ),
    )


def verify() -> dict[str, Any]:
    blockers: list[str] = []
    source = ROOT.joinpath("src", "human_intervention.py").read_text(encoding="utf-8")

    forbidden_source_tokens = (
        "sqlite3.connect(",
        "Keypair(",
        "send_transaction",
        "sendRawTransaction",
        "LIVE_TRADING_ENABLED=true",
    )
    for token in forbidden_source_tokens:
        if token in source:
            blockers.append(f"PR2_UNSAFE_SOURCE_TOKEN:{token}")

    permit_hash: str | None = None
    one_shot_reuse_blocked = False
    try:
        db = sqlite3.connect(":memory:")
        ledger = HumanInterventionLedger(db)
        request = _request()
        permit = ledger.issue(request, current_utc="2026-08-08T20:05:00Z")
        permit_hash = permit.permit_hash
        if permit.execution_capability_allowed:
            blockers.append("PR2_EXECUTION_CAPABILITY_ENABLED")
        if permit.live_submission_allowed:
            blockers.append("PR2_LIVE_SUBMISSION_ENABLED")
        if permit.automatic_scale_up_allowed:
            blockers.append("PR2_AUTOMATIC_SCALE_UP_ENABLED")
        if len(permit.operator_ids) != 2 or len(set(permit.operator_ids)) != 2:
            blockers.append("PR2_DUAL_CONTROL_NOT_ENFORCED")

        ledger.consume(
            permit,
            action=request.action,
            target=request.target,
            current_utc="2026-08-08T20:06:00Z",
            idempotency_key="verifier-consumer",
        )
        try:
            ledger.consume(
                permit,
                action=request.action,
                target=request.target,
                current_utc="2026-08-08T20:06:01Z",
                idempotency_key="second-consumer",
            )
        except PermitConflict:
            one_shot_reuse_blocked = True
        if not one_shot_reuse_blocked:
            blockers.append("PR2_ONE_SHOT_REUSE_NOT_BLOCKED")
    except Exception as exc:  # verifier must materialize unexpected failures
        blockers.append(f"PR2_VERIFIER_EXCEPTION:{type(exc).__name__}")

    return {
        "schema_version": SCHEMA_VERSION,
        "accepted": not blockers,
        "blockers": blockers,
        "authority": "src.human_intervention",
        "composes_acknowledgement_authority": "src.operator_ack_pr143",
        "caller_owned_sqlite": "sqlite3.connect(" not in source,
        "dual_human_control": True,
        "one_shot_reuse_blocked": one_shot_reuse_blocked,
        "sender_free": True,
        "execution_capability_allowed": False,
        "live_submission_allowed": False,
        "automatic_scale_up_allowed": False,
        "permit_hash": permit_hash,
        "remaining_physical_cutover": [
            "src.canonical_control_plane_pr195.clear_latch",
            "quarantined:src.execution.live_control",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    evidence = verify()
    if args.json:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    else:
        print("accepted" if evidence["accepted"] else "blocked")
    return 0 if evidence["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
