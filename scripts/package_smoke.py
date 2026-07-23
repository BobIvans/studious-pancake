#!/usr/bin/env python3
"""Build and validate the installed PR-025/PR-01 console package outside the repo."""

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

from src.production_surface import (
    assert_no_forbidden_wheel_members,
    required_entrypoints,
    required_wheel_members,
)

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


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> str:
    print(f"$ {' '.join(command)}", flush=True)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            command,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result.stdout


def _copy_source_tree(destination: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in IGNORED_COPY_NAMES or name.endswith(".egg-info")
        }

    shutil.copytree(ROOT, destination, ignore=ignore)


def _load_installed_authority(
    python: Path,
    *,
    cwd: Path,
    env: dict[str, str],
) -> dict[str, object]:
    output = _run(
        [
            str(python),
            "-c",
            (
                "import json; "
                "from src.authority_map import AuthorityMap; "
                "print(json.dumps(AuthorityMap.load_default().to_dict(), "
                "sort_keys=True))"
            ),
        ],
        cwd=cwd,
        env=env,
    )
    return json.loads(output)


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
            missing = sorted(required_wheel_members() - names)
            if missing:
                raise SystemExit(f"wheel is missing required files: {missing}")
            try:
                assert_no_forbidden_wheel_members(names)
            except RuntimeError as exc:
                raise SystemExit(str(exc)) from exc
            entry_points = [
                name for name in names if name.endswith(".dist-info/entry_points.txt")
            ]
            if len(entry_points) != 1:
                raise SystemExit("wheel does not contain one entry_points.txt")
            entry_text = archive.read(entry_points[0]).decode("utf-8")
            for executable, target in required_entrypoints().items():
                expected = f"{executable} = {target}"
                if expected not in entry_text:
                    raise SystemExit(
                        f"wheel entry point mismatch: expected {expected!r}"
                    )

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
        _run(
            [
                str(python),
                "-c",
                (
                    "from src.production_surface import "
                    "assert_forbidden_imports_unavailable; "
                    "assert_forbidden_imports_unavailable()"
                ),
            ],
            cwd=temporary,
            env=clean_env,
        )
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
        authority = _load_installed_authority(
            python,
            cwd=temporary,
            env=clean_env,
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
        if authority["schema_version"] != "pr01.authority-map.v1":
            raise SystemExit("installed package did not load the PR-01 authority map")
        if authority["product_state"] != "not-production-ready":
            raise SystemExit("installed authority map weakened the product state")
        entrypoint = authority["supported_entrypoint"]
        if not isinstance(entrypoint, dict) or entrypoint.get("target") != (
            "src.cli_pr189:main"
        ):
            raise SystemExit("installed authority map entrypoint does not match wheel")
        active = {
            vertical["roadmap_pr"]: vertical["active_branches"][0]
            for vertical in authority["verticals"]
            if vertical["active_branches"]
        }
        if active != {
            "PR-01": "roadmap/pr-01-repository-authority-consolidation",
            "PR-02": "roadmap/pr-02-unified-lifecycle-authority",
            "PR-03": "roadmap-pr-03-rooted-provider-admission",
            "PR-04": "pr-04-repeated-installed-paper-service",
        }:
            raise SystemExit("installed authority map has unexpected active branches")
        if any(
            vertical["active_branches"] or not vertical["hard_disabled"]
            for vertical in authority["verticals"][7:]
        ):
            raise SystemExit("installed authority map weakened PR-08 through PR-10")

    print("PR-087/PR-01 package boundary smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
