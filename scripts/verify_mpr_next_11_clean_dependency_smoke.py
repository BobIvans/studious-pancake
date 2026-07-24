#!/usr/bin/env python3
"""Fail-closed MPR-NEXT-11 clean dependency/package-smoke verifier scaffold."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA_VERSION = "mpr-next-11.clean-dependency-smoke.v0"
REQUIRED_STEPS = [
    "install requirements.txt",
    "install requirements-dev.txt",
    "build wheel from clean checkout",
    "install wheel into clean venv",
    "run package_smoke.py inside the prepared environment",
]


@dataclass(frozen=True)
class VerificationResult:
    schema_version: str
    ok: bool
    reason: str
    required_steps: list[str]
    violations: list[str]


def verify_clean_dependency_smoke(repo_root: Path) -> VerificationResult:
    violations = [
        "clean-venv build/install/smoke flow is not implemented yet",
        "package_smoke.py dependency preconditions are not normalized yet",
        "wheel install has not been proven isolated from ambient Python packages",
    ]
    return VerificationResult(
        schema_version=SCHEMA_VERSION,
        ok=False,
        reason="mpr_next_11_clean_dependency_smoke_not_implemented",
        required_steps=REQUIRED_STEPS,
        violations=violations,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = verify_clean_dependency_smoke(Path(args.repo_root).resolve())
    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    else:
        print(f"{result.schema_version}: ok={result.ok} reason={result.reason}")
        for violation in result.violations:
            print(f"- {violation}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
