#!/usr/bin/env python3
"""Fail-closed starter verifier for MPR-45 soak, fault and recovery evidence.

The real MPR-45 verifier must prove multi-day unique-cycle shadow soak,
fault-injection, restart/upgrade, alert and backup/restore qualification from
real installed-runtime artifacts. This scaffold refuses to pass until those
artifacts are present and independently verified.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


REQUIRED_REPORTS = (
    "multi_day_unique_cycle_shadow_soak",
    "fresh_provider_observation_continuity",
    "economic_shadow_reconciliation",
    "fault_injection_campaign",
    "restart_upgrade_campaign",
    "backup_restore_qualification",
    "alert_qualification",
    "independent_evidence_verification",
)


@dataclass(frozen=True)
class SoakFaultRecoveryResult:
    ok: bool
    status: str
    reason: str
    required_reports: tuple[str, ...]
    inspected_path: str | None = None


def verify_soak_fault_recovery(evidence_dir: Path | None) -> SoakFaultRecoveryResult:
    if evidence_dir is None:
        return SoakFaultRecoveryResult(
            ok=False,
            status="NOT_READY",
            reason="soak_fault_recovery_evidence_dir_required",
            required_reports=REQUIRED_REPORTS,
        )
    if not evidence_dir.exists():
        return SoakFaultRecoveryResult(
            ok=False,
            status="NOT_READY",
            reason="soak_fault_recovery_evidence_dir_missing",
            required_reports=REQUIRED_REPORTS,
            inspected_path=str(evidence_dir),
        )
    return SoakFaultRecoveryResult(
        ok=False,
        status="NOT_IMPLEMENTED",
        reason="mpr45_soak_fault_recovery_verifier_scaffold_only",
        required_reports=REQUIRED_REPORTS,
        inspected_path=str(evidence_dir),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = verify_soak_fault_recovery(args.evidence_dir)
    payload: dict[str, Any] = asdict(result)
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        print(f"{result.status}: {result.reason}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
