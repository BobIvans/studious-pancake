#!/usr/bin/env python3
"""Report the release-authority workflow and quarantine legacy PR workflows."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Sequence

SCHEMA_VERSION = "mpr-close-01.workflow-authority.v1"
FULL_SHA_RE = re.compile(r"@[0-9a-fA-F]{40}\b")
USES_RE = re.compile(r"^\s*-\s+uses:\s*([^\s#]+)|^\s*uses:\s*([^\s#]+)")
WAIVER_MARKER = "mpr-close-01-waive-moving-action"


@dataclass(frozen=True, slots=True)
class WorkflowUse:
    workflow: str
    line: int
    value: str
    pinned_full_sha: bool
    waived: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WorkflowReport:
    schema_version: str
    ok: bool
    strict: bool
    authority_workflows: tuple[str, ...]
    legacy_workflows: tuple[str, ...]
    uses: tuple[WorkflowUse, ...]
    violations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "strict": self.strict,
            "authority_workflows": list(self.authority_workflows),
            "legacy_workflows": list(self.legacy_workflows),
            "uses": [item.to_dict() for item in self.uses],
            "violations": list(self.violations),
            "release_authority_only": len(self.authority_workflows) == 1,
            "live_enabled": False,
            "signer_loaded": False,
            "sender_loaded": False,
        }


def _workflow_name(path: Path, text: str) -> str:
    for line in text.splitlines():
        if line.lower().startswith("name:"):
            return line.partition(":")[2].strip().strip('"\'')
    return path.name


def _is_authority(path: Path, text: str) -> bool:
    name = _workflow_name(path, text).lower()
    return path.name == "release-authority.yml" or name == "release authority"


def _scan_uses(path: Path, text: str) -> tuple[WorkflowUse, ...]:
    lines = text.splitlines()
    found: list[WorkflowUse] = []
    for index, line in enumerate(lines, start=1):
        match = USES_RE.search(line)
        if not match:
            continue
        value = (match.group(1) or match.group(2) or "").strip().strip('"\'')
        current_comment = line.partition("#")[2]
        previous = lines[index - 2] if index >= 2 else ""
        waived = WAIVER_MARKER in current_comment or WAIVER_MARKER in previous
        found.append(
            WorkflowUse(
                workflow=path.as_posix(),
                line=index,
                value=value,
                pinned_full_sha=bool(FULL_SHA_RE.search(value)),
                waived=waived,
            )
        )
    return tuple(found)


def evaluate_workflow_authority(root: Path, *, strict: bool = False) -> WorkflowReport:
    workflows_dir = root / ".github" / "workflows"
    workflow_paths = sorted(
        [
            *workflows_dir.glob("*.yml"),
            *workflows_dir.glob("*.yaml"),
        ]
    )
    authority: list[str] = []
    legacy: list[str] = []
    uses: list[WorkflowUse] = []
    violations: list[str] = []

    for path in workflow_paths:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(root).as_posix()
        if _is_authority(path, text):
            authority.append(rel)
        else:
            legacy.append(rel)
        uses.extend(_scan_uses(path.relative_to(root), text))

    if not authority:
        violations.append("missing .github/workflows/release-authority.yml")
    if len(authority) > 1:
        violations.append("more than one workflow claims release authority")

    authority_set = set(authority)
    for item in uses:
        if item.workflow in authority_set and not item.pinned_full_sha and not item.waived:
            violations.append(
                f"{item.workflow}:{item.line} uses moving action {item.value!r} without waiver"
            )

    return WorkflowReport(
        schema_version=SCHEMA_VERSION,
        ok=not violations,
        strict=strict,
        authority_workflows=tuple(authority),
        legacy_workflows=tuple(legacy),
        uses=tuple(uses),
        violations=tuple(violations),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repository root")
    parser.add_argument("--strict", action="store_true", help="fail on authority violations")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = evaluate_workflow_authority(Path(args.root), strict=args.strict)
    if args.as_json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(
            "WORKFLOW_AUTHORITY: "
            f"ok={str(report.ok).lower()} "
            f"authority={','.join(report.authority_workflows) or '-'} "
            f"legacy={len(report.legacy_workflows)} "
            "live=false signer=false sender=false"
        )
        for violation in report.violations:
            print(f"  - {violation}")
    return 1 if args.strict and not report.ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
