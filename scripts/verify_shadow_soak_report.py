#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mpr_close_04_runtime import run_shadow_soak_fixture, validate_shadow_soak


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify MPR-CLOSE-04 sender-free shadow soak report")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--report")
    args = parser.parse_args(argv)
    if args.report:
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    else:
        with tempfile.TemporaryDirectory() as tmp:
            report = run_shadow_soak_fixture(Path(tmp), 30)
    result = validate_shadow_soak(report, require_real=args.strict)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"accepted={result['accepted']}")
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
