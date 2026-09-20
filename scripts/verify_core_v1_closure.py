#!/usr/bin/env python3
"""Fail-closed architecture verifier for the ONE CORE CLOSURE PR."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.production_debt_profiles import evaluate_core_v1_profile_debt


def verify(root: Path = ROOT) -> dict[str, object]:
    report = evaluate_core_v1_profile_debt(repo_root=root)
    payload = report.to_dict()
    blockers = list(report.code_facts.blockers)
    payload["accepted_code_closure"] = not blockers and report.core_v1_code_complete
    payload["verifier_blockers"] = blockers
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = verify()
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            "CORE_V1_CODE_CLOSURE: "
            f"accepted={payload['accepted_code_closure']} "
            f"external_complete={payload['core_v1_external_qualification_complete']} "
            f"production_ready={payload['production_ready']}"
        )
    return 0 if payload["accepted_code_closure"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
