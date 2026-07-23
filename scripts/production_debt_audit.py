#!/usr/bin/env python3
"""Print or enforce production debt with optional release-qualification overlay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.automation_cli_pr189 import main as automation_main
from src.economic_authority_super_mpr_b import evaluate_super_mpr_b_evidence
from src.production_debt import evaluate_production_debt

QUALIFICATION_SCHEMA = "mpr-close-06.release-qualification.v1"
SUPER_MPR_B_EVIDENCE_BLOCKER_ID = "super-mpr-b.evidence-artifacts"


def _load_optional_qualification(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    if not candidate.is_file():
        return None
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    if payload.get("schema_version") != QUALIFICATION_SCHEMA:
        return None
    payload["_resolved_path"] = str(candidate)
    return payload


def _apply_qualification_overlay(
    payload: dict[str, Any],
    qualification: dict[str, Any] | None,
) -> dict[str, Any]:
    if not qualification:
        return payload

    resolved = qualification.get("debt_resolution", {})
    blockers = []
    resolved_ids: list[str] = []
    for blocker in payload.get("blockers", []):
        if resolved.get(blocker["id"], {}).get("resolved") is True:
            resolved_ids.append(blocker["id"])
            continue
        blockers.append(blocker)

    payload = dict(payload)
    payload["blockers"] = blockers
    payload["resolved_by_release_qualification"] = sorted(resolved_ids)
    payload["qualification"] = {
        "path": qualification.get("_resolved_path"),
        "release_id": qualification.get("release_id"),
        "qualified": bool(qualification.get("qualified")),
        "promotion_state": qualification.get("promotion_state"),
        "missing_artifacts": list(qualification.get("missing_artifacts", [])),
    }

    consistency_errors = list(payload.get("consistency_errors", []))
    payload["paper_ready"] = not consistency_errors and not any(
        row.get("blocks_paper") for row in blockers
    )
    payload["live_ready"] = not consistency_errors and not any(
        row.get("blocks_live") for row in blockers
    )
    observed = dict(payload.get("observed", {}))
    observed["qualification_path"] = qualification.get("_resolved_path")
    observed["qualification_release_id"] = qualification.get("release_id")
    payload["observed"] = observed
    payload["production_ready"] = (
        bool(qualification.get("qualified"))
        and payload["paper_ready"]
        and payload["live_ready"]
        and qualification.get("product_state") == "production-ready"
        and bool(qualification.get("live_mode_available"))
    )
    return payload


def _apply_super_mpr_b_evidence_overlay(
    payload: dict[str, Any],
    *,
    evidence_path: str,
) -> dict[str, Any]:
    evidence = evaluate_super_mpr_b_evidence(ROOT, evidence_path=evidence_path)
    payload = dict(payload)
    observed = dict(payload.get("observed", {}))
    observed["super_mpr_b_evidence"] = evidence
    payload["observed"] = observed

    blockers = list(payload.get("blockers", []))
    if not evidence["accepted"]:
        blockers.append(
            {
                "id": SUPER_MPR_B_EVIDENCE_BLOCKER_ID,
                "batch": "SUPER-MPR-B",
                "severity": "P0",
                "status": "evidence-pending",
                "title": "Durable economic authority evidence artifacts are missing or non-promotable",
                "surface": evidence["evidence_path"],
                "blocks_paper": True,
                "blocks_live": True,
                "observed_reason": ";".join(evidence["blockers"]),
                "required_actions": [
                    "materialize real wheel/image/SBOM/config/capability/database artifacts",
                    "attach real shadow-soak, fault-injection, and backup/restore reports",
                    "prove durable economic authority with non-synthetic evidence",
                ],
                "evidence_refs": [evidence["evidence_path"]],
            }
        )
    payload["blockers"] = blockers
    consistency_errors = list(payload.get("consistency_errors", []))
    payload["paper_ready"] = not consistency_errors and not any(
        row.get("blocks_paper") for row in blockers
    )
    payload["live_ready"] = not consistency_errors and not any(
        row.get("blocks_live") for row in blockers
    )
    payload["production_ready"] = bool(payload.get("production_ready")) and evidence["accepted"]
    return payload


def _legacy_main(
    *,
    as_json: bool,
    require_ready: bool,
    qualification_path: str | None,
    super_mpr_b_evidence: str,
) -> int:
    """Preserve the pre-PR-189 script payload and human-readable output."""

    report = evaluate_production_debt()
    payload = _apply_qualification_overlay(
        report.to_dict(),
        _load_optional_qualification(qualification_path),
    )
    payload = _apply_super_mpr_b_evidence_overlay(
        payload,
        evidence_path=super_mpr_b_evidence,
    )

    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"production_ready={payload['production_ready']}")
        print(f"paper_ready={payload['paper_ready']}")
        print(f"live_ready={payload['live_ready']}")
        print(f"blockers={len(payload['blockers'])}")
        for batch in payload["batches"]:
            print(f"{batch['id']}: open={batch['open_items']} p0={batch['p0_items']}")
        for error in payload["consistency_errors"]:
            print(f"CONSISTENCY_ERROR: {error}")

    if payload["consistency_errors"]:
        return 2
    if require_ready and not payload["production_ready"]:
        return 3
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", choices=("inspect", "check"))
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--check",
        action="store_true",
        dest="legacy_inventory_check",
        help="legacy consistency check; preserves the debt-report payload",
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="legacy readiness enforcement; preserves the historical output",
    )
    parser.add_argument(
        "--qualification",
        default=".runtime/release-qualification.json",
        help="optional MPR-CLOSE-06 release qualification overlay",
    )
    parser.add_argument(
        "--super-mpr-b-evidence",
        default="release_artifacts/super_mpr_b_evidence.json",
        help="SUPER-MPR-B evidence bundle consumed as a promotion blocker",
    )
    args = parser.parse_args(argv)

    if args.mode is None:
        return _legacy_main(
            as_json=args.as_json,
            require_ready=args.require_ready,
            qualification_path=args.qualification,
            super_mpr_b_evidence=args.super_mpr_b_evidence,
        )
    if args.require_ready and args.mode != "check":
        parser.error("--require-ready conflicts with explicit inspect mode")
    if args.legacy_inventory_check:
        parser.error("--check is a legacy flag; use the explicit check mode")
    return automation_main(["production-debt", args.mode])


if __name__ == "__main__":
    raise SystemExit(main())
