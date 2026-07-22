#!/usr/bin/env python3
"""Build D2 bundles with PR-189 explicit inspection/check modes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.automation_cli_pr189 import main as automation_main
from src.release_soak_artifacts_d2 import bundle_from_manifest, render_bundle_json


def _legacy_main(
    *,
    manifest: str,
    output: str | None,
    require_ready: bool,
) -> int:
    """Preserve the pre-PR-189 D2 bundle JSON and output-file behavior."""

    manifest_path = Path(manifest)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    bundle = bundle_from_manifest(data, base_dir=manifest_path.parent)
    rendered = render_bundle_json(bundle)
    if output:
        Path(output).write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if require_ready and bundle.blockers():
        return 3
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", choices=("inspect", "check"))
    parser.add_argument("--manifest", required=True, help="input JSON manifest")
    parser.add_argument("--output", default=None, help="optional output bundle JSON path")
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="legacy readiness enforcement; preserves the historical bundle schema",
    )
    args = parser.parse_args(argv)

    if args.mode is None:
        return _legacy_main(
            manifest=args.manifest,
            output=args.output,
            require_ready=args.require_ready,
        )
    if args.require_ready and args.mode != "check":
        parser.error("--require-ready conflicts with explicit inspect mode")
    if args.output:
        parser.error("--output is supported only by the legacy script surface")
    return automation_main(["release-soak", args.mode, "--manifest", args.manifest])


if __name__ == "__main__":
    raise SystemExit(main())
