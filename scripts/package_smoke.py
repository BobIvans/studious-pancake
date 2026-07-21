#!/usr/bin/env python3
"""Build and validate the installed PR-025 console package outside the repo."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]
IGNORED_COPY_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "venv",
}
FORBIDDEN_WHEEL_PATHS = frozenset(
    {
        "src/legacy_arb_bot.py",
        "src/execution/live_control.py",
        "src/execution/shadow.py",
    }
)
FORBIDDEN_WHEEL_PREFIXES = (
    "src/ingest/",
    "src/execution/senders/",
)


def _forbidden_wheel_members(names: set[str]) -> list[str]:
    return sorted(
        name
        for name in names
        if name in FORBIDDEN_WHEEL_PATHS
        or any(name.startswith(prefix) for prefix in FORBIDDEN_WHEEL_PREFIXES)
    )


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    print(f"$ {' '.join(command)}", flush=True)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.stdout


def _copy_source_tree(destination: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in IGNORED_COPY_NAMES or name.endswith(".egg-info")
        }

    shutil.copytree(ROOT, destination, ignore=ignore)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pr025-package-smoke-") as temp_dir:
        temporary = Path(temp_dir)
        source = temporary / "source"
        _copy_source_tree(source)

        dist = temporary / "dist"
        dist.mkdir()
        _run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(dist),
            ],
            cwd=source,
        )
        wheels = tuple(dist.glob("*.whl"))
        if len(wheels) != 1:
            raise SystemExit(f"expected exactly one wheel, found {len(wheels)}")
        wheel = wheels[0]
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
            required = {
                "arb_bot.py",
                "src/cli.py",
                "src/container_runtime.py",
                "src/resources/capabilities.json",
            }
            missing = sorted(required - names)
            if missing:
                raise SystemExit(f"wheel is missing required files: {missing}")
            forbidden = _forbidden_wheel_members(names)
            if forbidden:
                raise SystemExit(
                    "wheel contains quarantined production members: "
                    + ", ".join(forbidden)
                )
            entry_points = [
                name for name in names if name.endswith(".dist-info/entry_points.txt")
            ]
            if len(entry_points) != 1:
                raise SystemExit("wheel does not contain one entry_points.txt")
            entry_text = archive.read(entry_points[0]).decode("utf-8")
            for executable in ("flashloan-bot", "flashloan-bot-healthcheck"):
                if executable not in entry_text:
                    raise SystemExit(f"wheel entry point is missing: {executable}")

        environment = temporary / "venv"
        venv.EnvBuilder(with_pip=True, system_site_packages=False).create(environment)
        python = environment / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        bin_dir = python.parent
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "-r",
                str(source / "requirements.txt"),
            ],
            cwd=temporary,
        )
        _run(
            [str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
            cwd=temporary,
        )
        _run([str(python), "-m", "pip", "check"], cwd=temporary)
        clean_env = os.environ.copy()
        clean_env.pop("PYTHONPATH", None)
        clean_env["PATH"] = f"{bin_dir}{os.pathsep}{clean_env.get('PATH', '')}"
        clean_env["PYTHONNOUSERSITE"] = "1"
        status = json.loads(
            _run(
                [str(bin_dir / "flashloan-bot"), "status", "--json"],
                cwd=temporary,
                env=clean_env,
            )
        )
        capabilities = json.loads(
            _run(
                [str(bin_dir / "flashloan-bot"), "capabilities", "--json"],
                cwd=temporary,
                env=clean_env,
            )
        )
        if status["supported_entrypoint"] != "flashloan-bot":
            raise SystemExit("installed CLI reports an unexpected supported entrypoint")
        if capabilities["schema_version"] != "pr023.capabilities.v1":
            raise SystemExit(
                "installed package did not load the packaged capability registry"
            )
        if status["diagnostic"] != "NO_EXECUTABLE_STRATEGIES":
            raise SystemExit(
                "installed package did not preserve fail-closed runtime truth"
            )

    print("PR-087 package boundary smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
