"""Command-line interface for the PR-047 release gate."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Sequence

from pydantic import ValidationError

from .gate import ReleaseGate
from .models import ReleaseManifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pr047-release-gate")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="evaluate a release manifest")
    validate.add_argument("--manifest", required=True)
    validate.add_argument("--repo-root", default=".")

    manifest_hash = commands.add_parser(
        "hash", help="calculate canonical manifest hash"
    )
    manifest_hash.add_argument("--manifest", required=True)

    commands.add_parser("schema", help="print the strict JSON schema")
    return parser


def _load_manifest(path: str | Path) -> ReleaseManifest:
    return ReleaseManifest.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _git_commit(repo_root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    commit = completed.stdout.strip().lower()
    return commit or None


def _current_drift_ok() -> bool:
    registry_module = importlib.import_module("src.external_contracts.registry")
    drift_module = importlib.import_module("src.external_contracts.drift")
    registry = registry_module.ExternalContractRegistry.load_default()
    report = drift_module.detect_drift(registry)
    return bool(getattr(report, "ok", False))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "schema":
            print(
                json.dumps(
                    ReleaseManifest.model_json_schema(), indent=2, sort_keys=True
                )
            )
            return 0

        manifest = _load_manifest(args.manifest)
        if args.command == "hash":
            print(manifest.manifest_sha256)
            return 0

        repo_root = Path(args.repo_root).resolve()
        result = ReleaseGate(
            repo_root=repo_root,
            observed_code_commit=_git_commit(repo_root),
            observed_contract_drift_ok=_current_drift_ok(),
        ).evaluate(manifest)
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0 if result.production_ready else 2
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "pr047.release-gate-error.v1",
                    "state": "invalid",
                    "error": str(exc),
                    "production_ready": False,
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
