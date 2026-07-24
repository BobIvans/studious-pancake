#!/usr/bin/env python3
"""Fail-closed MPR-NEXT-11 workflow Python-version policy verifier scaffold."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEMA_VERSION = "mpr-next-11.workflow-python-policy.v0"
REQUIRED_PYTHON_POLICY = ">=3.13,<3.14"


@dataclass(frozen=True)
class VerificationResult:
    schema_version: str
    ok: bool
    reason: str
    required_python_policy: str
    violations: list[str]


def verify_python_policy(repo_root: Path) -> VerificationResult:
    violations = [
        "workflow Python-version scan is not implemented yet",
        "pyproject requires-python has not been compared against workflow setup-python values",
        "release workflows have not been normalized to one supported Python 3.13 policy",
    ]
    return VerificationResult(
        schema_version=SCHEMA_VERSION,
        ok=False,
        reason="mpr_next_11_workflow_python_policy_not_implemented",
        required_python_policy=REQUIRED_PYTHON_POLICY,
        violations=violations,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = verify_python_policy(Path(args.repo_root).resolve())
    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
    else:
        print(f"{result.schema_version}: ok={result.ok} reason={result.reason}")
        for violation in result.violations:
            print(f"- {violation}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
