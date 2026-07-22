#!/usr/bin/env python3
"""Build a MEGA-PR D2 release/soak evidence bundle from real artifact files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.release_soak_artifacts_d2 import bundle_from_manifest, render_bundle_json


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, help="input JSON manifest")
    parser.add_argument("--output", default=None, help="optional output bundle JSON path")
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="exit non-zero unless bundle is ready-for-review",
    )
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    bundle = bundle_from_manifest(data, base_dir=manifest_path.parent)
    rendered = render_bundle_json(bundle)
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if args.require_ready and bundle.blockers():
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
