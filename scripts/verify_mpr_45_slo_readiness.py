#!/usr/bin/env python3
"""Fail-closed starter verifier for MPR-45 SLO/readiness evidence.

MPR-45 requires readiness to come from service truth, not process liveness or
self-declared booleans. This scaffold is deliberately NOT_READY until it is
wired to installed-runtime health, task, provider, DB, queue, disk and release
state artifacts.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


REQUIRED_SIGNALS = (
    "active_task_generations",
    "trusted_time_health",
    "provider_rpc_freshness",
    "database_writer_fence",
    "migration_schema_state",
    "queue_backlog_thresholds",
    "disk_wal_pressure",
    "configuration_validity",
    "release_capability_state",
)


@dataclass(frozen=True)
class ReadinessResult:
    ok: bool
    status: str
    reason: str
    required_signals: tuple[str, ...]
    inspected_path: str | None = None


def verify_slo_readiness(evidence_path: Path | None) -> ReadinessResult:
    if evidence_path is None:
        return ReadinessResult(
            ok=False,
            status="NOT_READY",
            reason="slo_readiness_evidence_path_required",
            required_signals=REQUIRED_SIGNALS,
        )
    if not evidence_path.exists():
        return ReadinessResult(
            ok=False,
            status="NOT_READY",
            reason="slo_readiness_evidence_missing",
            required_signals=REQUIRED_SIGNALS,
            inspected_path=str(evidence_path),
        )
    return ReadinessResult(
        ok=False,
        status="NOT_IMPLEMENTED",
        reason="mpr45_slo_readiness_verifier_scaffold_only",
        required_signals=REQUIRED_SIGNALS,
        inspected_path=str(evidence_path),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = verify_slo_readiness(args.evidence)
    payload: dict[str, Any] = asdict(result)
    if args.json:
        print(json.dumps(payload, sort_keys=True, indent=2))
    else:
        print(f"{result.status}: {result.reason}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
