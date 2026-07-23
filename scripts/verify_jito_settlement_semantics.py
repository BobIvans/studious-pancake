#!/usr/bin/env python3
"""Verify MPR-CLOSE-05 conservative Jito settlement semantics offline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.jito_settlement_semantics import (  # noqa: E402
    JitoSettlementEvidence,
    JitoSettlementState,
    evaluate_jito_settlement,
)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _evidence(**overrides: object) -> JitoSettlementEvidence:
    message_hash = _hash("message")
    values = {
        "attempt_id": "attempt-1",
        "message_sha256": message_hash,
        "exact_simulation_hash": message_hash,
        "local_simulation_passed": True,
        "skip_preflight": True,
        "transport_ack_received": True,
        "bundle_id": _hash("bundle"),
        "bundle_status": "Landed",
        "signature_status": "finalized",
        "finalized_reconciliation_hash": _hash("finalized-reconciliation"),
        "finalized_reconciliation_passed": True,
        "tip_lamports": 10_000,
        "minimum_tip_lamports": 1_000,
        "max_tip_lamports": 50_000,
        "tip_in_primary_transaction": True,
        "standalone_tip_transaction": False,
        "unbundling_protection_present": True,
        "uncled_block_protection_present": True,
    }
    values.update(overrides)
    return JitoSettlementEvidence(**values)


def verify() -> dict[str, object]:
    finalized = evaluate_jito_settlement(_evidence())
    ack_only = evaluate_jito_settlement(
        _evidence(
            bundle_status="Pending",
            signature_status="confirmed",
            finalized_reconciliation_hash=None,
            finalized_reconciliation_passed=False,
        )
    )
    unsafe = evaluate_jito_settlement(
        _evidence(
            local_simulation_passed=False,
            tip_lamports=100,
            standalone_tip_transaction=True,
            tip_in_primary_transaction=False,
            unbundling_protection_present=False,
        )
    )
    accepted = bool(
        finalized.state is JitoSettlementState.FINALIZED
        and finalized.finalized
        and not finalized.ack_is_settlement
        and not finalized.bundle_id_is_settlement
        and ack_only.state is JitoSettlementState.ACK_ONLY
        and not ack_only.finalized
        and unsafe.state is JitoSettlementState.BLOCKED
        and any(
            item.code == "JITO_SKIP_PREFLIGHT_REQUIRES_LOCAL_SIMULATION"
            for item in unsafe.blockers
        )
    )
    return {
        "schema_version": "mpr-close-05.verify-jito-settlement-semantics.v1",
        "accepted": accepted,
        "finalized_report": finalized.to_dict(),
        "ack_only_report": ack_only.to_dict(),
        "unsafe_report": unsafe.to_dict(),
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
