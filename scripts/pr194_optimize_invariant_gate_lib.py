"""PR-194 optimize-mode invariant gate implementation.

Python removes ``assert`` statements when code is executed with ``-O``. Production
validation and security controls therefore must not rely on ``assert`` for any
runtime invariant that is expected to survive optimized execution.

This helper stays under ``scripts`` so the PR-194 gate can run in CI without
expanding the installed runtime/package surface.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

EVIDENCE_SCHEMA = "pr194.optimize-invariant-gate.v1"

PRODUCTION_CRITICAL_PATHS: tuple[str, ...] = (
    "arb_bot.py",
    "src/production_surface.py",
    "scripts/package_smoke.py",
    "scripts/verify_repo.py",
)

EXCLUDED_PATH_PREFIXES: tuple[str, ...] = (
    "tests/",
    "build/",
    "dist/",
    ".git/",
    ".mypy_cache/",
    ".pytest_cache/",
)


@dataclass(frozen=True, slots=True)
class OptimizeInvariantViolation:
    """A production-critical ``assert`` that would disappear under ``python -O``."""

    path: str
    line: int
    column: int
    reason: str = "assert_removed_by_python_optimize_mode"

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "reason": self.reason,
        }


def normalize_repository_path(path: str | Path) -> str:
    """Return a stable POSIX-style repository path for evidence payloads."""

    return Path(path).as_posix().lstrip("./")


def is_excluded_path(path: str | Path) -> bool:
    """Return true when a path is intentionally outside the production gate."""

    normalized = normalize_repository_path(path)
    return any(normalized.startswith(prefix) for prefix in EXCLUDED_PATH_PREFIXES)


def scan_source_text(
    path: str | Path,
    source: str,
) -> tuple[OptimizeInvariantViolation, ...]:
    """Find ``assert`` statements in one Python source string."""

    normalized = normalize_repository_path(path)
    if is_excluded_path(normalized):
        return ()

    tree = ast.parse(source, filename=normalized)
    violations = [
        OptimizeInvariantViolation(
            path=normalized,
            line=node.lineno,
            column=node.col_offset,
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.Assert)
    ]
    return tuple(
        sorted(violations, key=lambda item: (item.path, item.line, item.column))
    )


def scan_file(path: Path, *, root: Path) -> tuple[OptimizeInvariantViolation, ...]:
    """Scan one Python file and report optimize-mode invariant violations."""

    relative = normalize_repository_path(path.relative_to(root))
    if is_excluded_path(relative) or path.suffix != ".py":
        return ()
    return scan_source_text(relative, path.read_text(encoding="utf-8"))


def scan_paths(
    root: Path,
    paths: Iterable[str | Path] = PRODUCTION_CRITICAL_PATHS,
) -> tuple[OptimizeInvariantViolation, ...]:
    """Scan declared production-critical paths under *root*.

    Missing paths are reported as deterministic violations instead of being
    silently ignored, because a missing authority file means the gate did not
    inspect the artifact it was asked to prove.
    """

    violations: list[OptimizeInvariantViolation] = []
    for raw_path in paths:
        normalized = normalize_repository_path(raw_path)
        candidate = root / normalized
        if not candidate.exists():
            violations.append(
                OptimizeInvariantViolation(
                    path=normalized,
                    line=0,
                    column=0,
                    reason="production_critical_path_missing",
                )
            )
            continue
        if candidate.is_dir():
            for file_path in sorted(candidate.rglob("*.py")):
                violations.extend(scan_file(file_path, root=root))
        else:
            violations.extend(scan_file(candidate, root=root))
    return tuple(
        sorted(violations, key=lambda item: (item.path, item.line, item.column))
    )


def build_evidence(
    root: Path,
    paths: Sequence[str | Path] = PRODUCTION_CRITICAL_PATHS,
) -> dict[str, Any]:
    """Build deterministic PR-194 optimize-mode evidence."""

    normalized_paths = tuple(normalize_repository_path(path) for path in paths)
    violations = scan_paths(root, normalized_paths)
    return {
        "schema_version": EVIDENCE_SCHEMA,
        "ready": not violations,
        "checked_paths": list(normalized_paths),
        "violation_count": len(violations),
        "violations": [violation.to_dict() for violation in violations],
        "safety_boundary": {
            "live_trading_enabled": False,
            "sender_free": True,
            "network_calls": False,
            "signer_or_private_key_access": False,
        },
    }
