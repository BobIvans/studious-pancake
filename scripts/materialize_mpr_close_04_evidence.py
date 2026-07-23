#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.mpr_close_04_runtime import materialize_evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize MPR-CLOSE-04 evidence bundle")
    parser.add_argument("--output-dir", default=".runtime/evidence/mpr-close-04")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(materialize_evidence(Path(args.output_dir)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
