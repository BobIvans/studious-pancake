#!/usr/bin/env python3
"""Validate the NEW-MEGA-PR-01 canonical runtime authority map."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtime_authority_pr01 import evaluate_runtime_authority_map


def _load(path: str | None) -> dict[str, object] | None:
    if not path:
        return None
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return json.loads(candidate.read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--map",
        default=None,
        help="optional runtime authority map JSON; defaults to packaged resource",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = evaluate_runtime_authority_map(_load(args.map))
    payload = report.to_dict()
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"accepted={payload['accepted']}")
        print(f"active_composition_root={payload['active_composition_root']}")
        print(f"lifecycle_authority={payload['lifecycle_authority']}")
        print(f"capital_authority={payload['capital_authority']}")
        print(f"blockers={len(payload['blockers'])}")
        for blocker in payload["blockers"]:
            print(f"BLOCKER: {blocker}")
    return 0 if report.accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
