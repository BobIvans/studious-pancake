#!/usr/bin/env python3
"""Regenerate PR-025 requirement locks from ``pyproject.toml`` with uv.

The public runtime and analytics profiles are compiled directly from the project
metadata. The service and developer extras are compiled independently and then
merged with the two public profiles. Splitting the large developer resolution
keeps the process bounded on slow package indexes while preserving a single
source of truth in ``pyproject.toml``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_PYTHON = (3, 13)
UV_VERSION = "0.10.0"
PIN_RE = re.compile(
    r"^([A-Za-z0-9_.-]+)(?:\[[A-Za-z0-9_,.-]+\])?==([^\s;]+)(.*)$"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _uv_version(uv: str) -> str:
    result = subprocess.run(
        [uv, "--version"], check=True, capture_output=True, text=True
    )
    parts = result.stdout.strip().split()
    return parts[-1] if parts else ""


def _run_compile(
    uv: str,
    source: Path,
    output: Path,
    *,
    extras: Iterable[str] = (),
    upgrade: bool,
) -> None:
    output.unlink(missing_ok=True)
    command = [
        uv,
        "pip",
        "compile",
        str(source),
        "--python-version",
        "3.13",
        "--no-emit-index-url",
        "--no-emit-find-links",
        "--output-file",
        str(output),
    ]
    if upgrade:
        command.append("--upgrade")
    for extra in extras:
        command.extend(("--extra", extra))
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def _read_project() -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    project = data.get("project")
    if not isinstance(project, dict):
        raise SystemExit("pyproject.toml is missing [project]")
    return project


def _write_group_input(project: dict[str, object], group: str, path: Path) -> None:
    optional = project.get("optional-dependencies")
    if not isinstance(optional, dict) or not isinstance(optional.get(group), list):
        raise SystemExit(
            f"pyproject.toml is missing optional dependency group {group!r}"
        )
    requirements = optional[group]
    path.write_text(
        "\n".join(str(item) for item in requirements) + "\n", encoding="utf-8"
    )


def _parse_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        match = PIN_RE.match(line)
        if match is None:
            raise SystemExit(f"unexpected non-exact requirement in {path}: {line}")
        name, version, suffix = match.groups()
        pins[_canonical_name(name)] = f"{name}=={version}{suffix}"
    return pins


def _direct_versions(project: dict[str, object]) -> dict[str, str]:
    values: list[str] = []
    dependencies = project.get("dependencies")
    if isinstance(dependencies, list):
        values.extend(str(item) for item in dependencies)
    optional = project.get("optional-dependencies")
    if isinstance(optional, dict):
        for group in ("analytics", "service", "dev"):
            entries = optional.get(group)
            if isinstance(entries, list):
                values.extend(str(item) for item in entries)
    direct: dict[str, str] = {}
    for value in values:
        match = PIN_RE.match(value)
        if match is None:
            raise SystemExit(
                f"all PR-025 direct dependencies must be exact pins: {value}"
            )
        name, version, suffix = match.groups()
        direct[_canonical_name(name)] = f"{name}=={version}{suffix}"
    return direct


def _write_merged_dev_lock(
    output: Path,
    *,
    project: dict[str, object],
    component_locks: Sequence[Path],
) -> None:
    candidates: dict[str, set[str]] = {}
    for lock in component_locks:
        for name, pin in _parse_pins(lock).items():
            candidates.setdefault(name, set()).add(pin)

    direct = _direct_versions(project)
    merged: dict[str, str] = {}
    for name, choices in sorted(candidates.items()):
        direct_pin = direct.get(name)
        if direct_pin is not None:
            merged[name] = direct_pin
            continue
        if len(choices) == 1:
            merged[name] = next(iter(choices))
            continue
        rendered = ", ".join(sorted(choices))
        raise SystemExit(
            f"transitive dependency conflict while merging developer lock: "
            f"{name}: {rendered}"
        )

    header = [
        "# This file is autogenerated by scripts/lock_requirements.py with uv 0.10.0.",
        "# Source: pyproject.toml; profiles: runtime + analytics + service + dev.",
        "# Target: CPython 3.13 on supported Linux/macOS runtime platforms.",
        "",
    ]
    output.write_text(
        "\n".join(header + [merged[name] for name in sorted(merged)]) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="Allow newer versions permitted by pyproject.toml.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if sys.version_info[:2] != SUPPORTED_PYTHON:
        version = ".".join(map(str, sys.version_info[:3]))
        raise SystemExit(
            f"lock generation requires Python 3.13.x, current interpreter is {version}"
        )
    uv = shutil.which("uv")
    if uv is None:
        raise SystemExit(f"uv=={UV_VERSION} is required; install the dev profile first")
    actual_version = _uv_version(uv)
    if actual_version != UV_VERSION:
        raise SystemExit(
            f"lock generation requires uv=={UV_VERSION}, found {actual_version}"
        )

    project = _read_project()
    runtime_lock = ROOT / "requirements.txt"
    analytics_lock = ROOT / "requirements-analytics.txt"
    dev_lock = ROOT / "requirements-dev.txt"

    with tempfile.TemporaryDirectory(prefix="pr025-lock-") as temp_dir:
        temporary = Path(temp_dir)
        service_input = temporary / "service.in"
        developer_input = temporary / "dev.in"
        service_lock = temporary / "service.txt"
        developer_lock = temporary / "dev.txt"
        _write_group_input(project, "service", service_input)
        _write_group_input(project, "dev", developer_input)

        _run_compile(
            uv,
            ROOT / "pyproject.toml",
            runtime_lock,
            upgrade=args.upgrade,
        )
        _run_compile(
            uv,
            ROOT / "pyproject.toml",
            analytics_lock,
            extras=("analytics",),
            upgrade=args.upgrade,
        )
        _run_compile(uv, service_input, service_lock, upgrade=args.upgrade)
        _run_compile(uv, developer_input, developer_lock, upgrade=args.upgrade)
        _write_merged_dev_lock(
            dev_lock,
            project=project,
            component_locks=(
                developer_lock,
                service_lock,
                analytics_lock,
                runtime_lock,
            ),
        )

    manifest = {
        "schema_version": "pr025.requirements-lock.v1",
        "python": "3.13",
        "platforms": ["linux", "macos"],
        "resolver": {"name": "uv", "version": actual_version},
        "source": "pyproject.toml",
        "locks": {
            "requirements.txt": {
                "extras": [],
                "sha256": _sha256(runtime_lock),
            },
            "requirements-analytics.txt": {
                "extras": ["analytics"],
                "sha256": _sha256(analytics_lock),
            },
            "requirements-dev.txt": {
                "extras": ["analytics", "service", "dev"],
                "sha256": _sha256(dev_lock),
            },
        },
    }
    (ROOT / "config/requirements-lock.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
