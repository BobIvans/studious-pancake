#!/usr/bin/env python3
"""Verify MPR-CLOSE-05 bounded canary latches offline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.release_gate.mpr_close_05_canary import (  # noqa: E402
    CanaryLatchEvidence,
    CanaryLatchState,
    HumanApproval,
    UpstreamEvidenceRef,
    evaluate_canary_latches,
)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _approval(principal: str, message_hash: str) -> HumanApproval:
    return HumanApproval(
        principal_id=principal,
        approval_hash=_hash("approval:" + principal),
        message_sha256=message_hash,
        issued_at_ns=100,
        expires_at_ns=1_000,
        independent=True,
        fresh=True,
    )


def _evidence(**overrides: object) -> CanaryLatchEvidence:
    message_hash = _hash("message")
    values = {
        "upstream_evidence": tuple(
            UpstreamEvidenceRef(name, _hash(name), accepted=True, fresh=True)
            for name in (
                "MPR-CLOSE-01",
                "MPR-CLOSE-02",
                "MPR-CLOSE-03",
                "MPR-CLOSE-04",
            )
        ),
        "production_cutover_manifest_hash": _hash("cutover"),
        "provider_drift_report_hash": _hash("provider-drift"),
        "exact_message_sha256": message_hash,
        "exact_message_proof_hash": _hash("message-proof"),
        "canary_policy_hash": _hash("canary-policy"),
        "outstanding_attempts_unknown": False,
        "emergency_stop_clear": True,
        "second_human_approval_required": True,
        "approvals": (_approval("alice", message_hash), _approval("bob", message_hash)),
        "capital_cap_lamports": 10_000_000,
        "per_trade_cap_lamports": 1_000_000,
        "daily_loss_cap_lamports": 500_000,
        "requested_capital_lamports": 2_000_000,
        "requested_trade_lamports": 250_000,
        "realized_daily_loss_lamports": 0,
        "automatic_stop_after_first_failure": True,
        "automatic_stop_after_budget_exhausted": True,
        "canary_enabled_by_default": False,
        "unrestricted_live_requested": False,
    }
    values.update(overrides)
    return CanaryLatchEvidence(**values)


def verify() -> dict[str, object]:
    ready = evaluate_canary_latches(_evidence())
    missing_upstream = evaluate_canary_latches(
        _evidence(
            upstream_evidence=(
                UpstreamEvidenceRef("MPR-CLOSE-01", _hash("MPR-CLOSE-01"), True, True),
            )
        )
    )
    unsafe_live = evaluate_canary_latches(
        _evidence(canary_enabled_by_default=True, unrestricted_live_requested=True)
    )
    over_budget = evaluate_canary_latches(
        _evidence(requested_trade_lamports=2_000_000)
    )
    accepted = bool(
        ready.state is CanaryLatchState.READY_FOR_BOUNDED_CANARY
        and ready.canary_allowed
        and not ready.unrestricted_live_allowed
        and missing_upstream.state is CanaryLatchState.BLOCKED
        and unsafe_live.state is CanaryLatchState.BLOCKED
        and over_budget.state is CanaryLatchState.BLOCKED
    )
    return {
        "schema_version": "mpr-close-05.verify-canary-latches.v1",
        "accepted": accepted,
        "ready_report": ready.to_dict(),
        "missing_upstream_report": missing_upstream.to_dict(),
        "unsafe_live_report": unsafe_live.to_dict(),
        "over_budget_report": over_budget.to_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = verify()
    if args.json:
        print(json.dumps(report, sort_keys=True, indent=2))
    else:
        print("accepted=" + str(report["accepted"]).lower())
    return 0 if report["accepted"] or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
