#!/usr/bin/env python3
"""Evaluate one MPR-NEXT-07 debt-closure evidence JSON bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.readiness.debt_closure_map import (  # noqa: E402
    GATE_DEBT_MAP,
    closure_map_digest,
    evaluate_debt_closure_evidence,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate fail-closed debt-closure evidence."
    )
    parser.add_argument(
        "--evidence",
        help="JSON evidence bundle to evaluate; omit to print the static map digest",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    if not args.evidence:
        payload = {
            "closure_map_digest": closure_map_digest(),
            "known_gates": sorted(GATE_DEBT_MAP),
            "production_ready": False,
            "paper_ready": False,
            "live_ready": False,
        }
        if args.as_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"closure_map_digest={payload['closure_map_digest']}")
            print(f"known_gates={','.join(payload['known_gates'])}")
        return 0

    evidence_path = Path(args.evidence)
    if not evidence_path.is_absolute():
        evidence_path = ROOT / evidence_path
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    decision = evaluate_debt_closure_evidence(evidence)
    payload = decision.to_dict()
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"debt_closure_ok={str(decision.ok).lower()}")
        print(f"resolved={len(decision.resolved_debt_ids)}")
        print(f"blocked={len(decision.blocked_debt_ids)}")
        for violation in decision.violations:
            print(f"VIOLATION {violation.code}: {violation.detail}")
    return 0 if decision.ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
