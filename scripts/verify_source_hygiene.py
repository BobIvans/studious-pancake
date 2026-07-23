#!/usr/bin/env python3
"""Fail closed when generated artifacts are present in the source tree.

MPR-CLOSE-01 treats source hygiene as release evidence.  The check is intentionally
offline and deterministic: it scans the checkout and reports committed/runtime
byproducts that must never be part of a production artifact.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Iterable, Sequence

SCHEMA_VERSION = "mpr-close-01.source-hygiene.v1"

FORBIDDEN_DIR_NAMES = frozenset(
    {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "build",
        "dist",
    }
)
FORBIDDEN_SUFFIXES = frozenset(
    {
        ".pyc",
        ".pyo",
        ".log",
    }
)
FORBIDDEN_FILE_NAMES = frozenset(
    {
        ".coverage",
    }
)
SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "ENV",
        "node_modules",
    }
)


@dataclass(frozen=True, slots=True)
class HygieneViolation:
    path: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class HygieneReport:
    schema_version: str
    ok: bool
    strict: bool
    checked_root: str
    violations: tuple[HygieneViolation, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "strict": self.strict,
            "checked_root": self.checked_root,
            "violations": [item.to_dict() for item in self.violations],
            "live_enabled": False,
            "signer_loaded": False,
            "sender_loaded": False,
        }


def _is_egg_info(path: Path) -> bool:
    return path.name.endswith(".egg-info")


def _reason_for(path: Path) -> str | None:
    name = path.name
    if path.is_dir() and (name in FORBIDDEN_DIR_NAMES or _is_egg_info(path)):
        return "forbidden generated directory"
    if path.is_file() and (
        name in FORBIDDEN_FILE_NAMES or path.suffix in FORBIDDEN_SUFFIXES
    ):
        return "forbidden generated file"
    return None


def _skip_children(path: Path) -> bool:
    if path.name in SKIP_DIR_NAMES:
        return True
    # Release evidence is intentionally produced under .runtime and release_artifacts;
    # this script guards source-control hygiene, not local generated evidence.
    return path.name in {".runtime", "release_artifacts"}


def iter_violations(root: Path) -> Iterable[HygieneViolation]:
    stack = [root]
    while stack:
        current = stack.pop()
        if current != root and _skip_children(current):
            continue
        try:
            children = list(current.iterdir())
        except (FileNotFoundError, PermissionError):
            continue
        for child in children:
            rel = child.relative_to(root).as_posix()
            reason = _reason_for(child)
            if reason is not None:
                yield HygieneViolation(rel, reason)
            if child.is_dir():
                stack.append(child)


def evaluate_source_hygiene(root: Path, *, strict: bool = False) -> HygieneReport:
    checked_root = root.resolve()
    violations = tuple(sorted(iter_violations(checked_root), key=lambda item: item.path))
    return HygieneReport(
        schema_version=SCHEMA_VERSION,
        ok=not violations,
        strict=strict,
        checked_root=str(checked_root),
        violations=violations,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repository root to scan")
    parser.add_argument("--strict", action="store_true", help="return non-zero on violations")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = evaluate_source_hygiene(Path(args.root), strict=args.strict)
    payload = report.to_dict()
    if args.as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            "SOURCE_HYGIENE: "
            f"ok={str(report.ok).lower()} "
            f"violations={len(report.violations)} "
            "live=false signer=false sender=false"
        )
        for violation in report.violations:
            print(f"  - {violation.path}: {violation.reason}")
    return 1 if args.strict and not report.ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
