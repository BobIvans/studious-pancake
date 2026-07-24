#!/usr/bin/env python3
"""Validate MPR-NEXT-03 provider/protocol conformance evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.provider_protocol_conformance_mpr_next_03 import (  # noqa: E402
    evaluate_provider_conformance,
    load_manifest,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(list(argv) if argv is not None else None)

    manifest = load_manifest(args.manifest) if args.manifest else None
    report = evaluate_provider_conformance(manifest)
    payload = report.to_dict()
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"accepted={payload['accepted']}")
        print(f"provider_count={payload['provider_count']}")
        print(f"drift_artifact_count={payload['drift_artifact_count']}")
        for blocker in payload["blockers"]:
            print(f"BLOCKER: {blocker}")
    return 0 if report.accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
