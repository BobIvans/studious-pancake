#!/usr/bin/env python3
"""Verify MPR-41 trusted data-plane evidence or inspect its static contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_plane.mpr41_trusted_provider_data_plane import (  # noqa: E402
    bundle_from_mapping,
    evaluate_mpr41_evidence,
    scan_paths_for_network_bypasses,
    static_contract,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", help="JSON evidence bundle to evaluate")
    parser.add_argument(
        "--scan-path",
        action="append",
        default=[],
        help="Python file or directory to scan for direct network bypasses",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--require-clean-scan",
        action="store_true",
        help="exit non-zero when --scan-path finds bypasses",
    )
    args = parser.parse_args(argv)

    payload: dict[str, object] = {"contract": static_contract()}
    exit_code = 0

    if args.evidence:
        evidence_path = Path(args.evidence)
        if not evidence_path.is_absolute():
            evidence_path = ROOT / evidence_path
        bundle = bundle_from_mapping(json.loads(evidence_path.read_text(encoding="utf-8")))
        decision = evaluate_mpr41_evidence(bundle)
        payload["evidence_path"] = str(evidence_path)
        payload["decision"] = decision.to_dict()
        if not decision.accepted:
            exit_code = 1

    if args.scan_path:
        paths = [Path(path) if Path(path).is_absolute() else ROOT / path for path in args.scan_path]
        findings = scan_paths_for_network_bypasses(paths)
        payload["network_bypass_scan"] = {
            "paths": [str(path) for path in paths],
            "findings": [finding.to_dict() for finding in findings],
            "clean": not findings,
        }
        if findings and args.require_clean_scan:
            exit_code = 2

    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        contract = payload["contract"]
        assert isinstance(contract, dict)
        print(f"schema_version={contract['schema_version']}")
        print(f"mpr_id={contract['mpr_id']}")
        print(f"evidence_kind={contract['evidence_kind']}")
        print(f"default_off={contract['default_off']}")
        if "decision" in payload:
            decision = payload["decision"]
            assert isinstance(decision, dict)
            print(f"accepted={decision['accepted']}")
            print(f"reason_codes={','.join(decision['reason_codes'])}")
        if "network_bypass_scan" in payload:
            scan = payload["network_bypass_scan"]
            assert isinstance(scan, dict)
            print(f"network_bypass_clean={scan['clean']}")
            print(f"network_bypass_findings={len(scan['findings'])}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
