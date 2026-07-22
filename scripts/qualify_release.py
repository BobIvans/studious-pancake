#!/usr/bin/env python3
"""PR-176 one-command qualification wrapper."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.qualification_pr176 import build_default_qualification_plan, sha256_text


def _source_digest() -> str:
    return sha256_text(
        "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                ROOT / "pyproject.toml",
                ROOT / "requirements.txt",
                ROOT / "requirements-dev.txt",
            )
            if path.exists()
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--profile", action="append", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)

    plan = build_default_qualification_plan(ROOT)
    manifest = plan.to_manifest(
        source_digest=_source_digest(),
        execution_mode="execute" if args.execute else "dry-run",
    )
    rendered = json.dumps(manifest, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)

    if not args.execute:
        return 0

    by_name = {profile.name: profile for profile in plan.profiles}
    selected = set(args.profile or plan.mandatory_profiles)
    unknown = sorted(selected.difference(by_name))
    if unknown:
        raise SystemExit(f"unknown qualification profile(s): {unknown}")
    for name in sorted(selected):
        completed = subprocess.run(by_name[name].command, cwd=ROOT, check=False)
        if completed.returncode:
            raise SystemExit(completed.returncode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
