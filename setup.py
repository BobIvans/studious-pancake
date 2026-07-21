"""Production package boundary customisations.

PR-087 keeps legacy/quarantined source files in the repository for migration
and forensic review, but prevents them from being emitted into the installed
runtime wheel. The supported production wheel remains sender-free and
live-disabled.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py

FORBIDDEN_PRODUCTION_MODULES: frozenset[tuple[str, str]] = frozenset(
    {
        ("src", "legacy_arb_bot"),
        ("src.execution", "live_control"),
        ("src.execution", "shadow"),
    }
)

FORBIDDEN_PRODUCTION_PACKAGE_PREFIXES: tuple[str, ...] = (
    "src.ingest",
    "src.execution.senders",
)


def _is_forbidden_package(package: str) -> bool:
    return any(
        package == prefix or package.startswith(f"{prefix}.")
        for prefix in FORBIDDEN_PRODUCTION_PACKAGE_PREFIXES
    )


def _is_forbidden_module(package: str, module: str) -> bool:
    return _is_forbidden_package(package) or (
        package,
        module,
    ) in FORBIDDEN_PRODUCTION_MODULES


class ProductionBoundaryBuildPy(_build_py):
    """Build command that strips quarantined modules from runtime wheels."""

    def find_package_modules(
        self,
        package: str,
        package_dir: str,
    ) -> list[tuple[str, str, str]]:
        modules = super().find_package_modules(package, package_dir)
        return [
            module
            for module in modules
            if not _is_forbidden_module(module[0], module[1])
        ]

    def find_modules(self) -> list[tuple[str, str, str]]:
        modules = super().find_modules()
        return [
            module
            for module in modules
            if not _is_forbidden_module(module[0], module[1])
        ]

    def find_all_modules(self) -> list[tuple[str, str, str]]:
        modules = super().find_all_modules()
        return [
            module
            for module in modules
            if not _is_forbidden_module(module[0], module[1])
        ]

    def build_module(
        self,
        module: str,
        module_file: str,
        package: str | None,
    ) -> tuple[str, bool] | None:
        if package and _is_forbidden_module(package, module):
            return None
        return super().build_module(module, module_file, package)

    def build_package_data(self) -> None:
        super().build_package_data()
        self._remove_forbidden_outputs()

    def run(self) -> None:
        super().run()
        self._remove_forbidden_outputs()

    def _remove_forbidden_outputs(self) -> None:
        build_lib = Path(self.build_lib)
        for relative in _forbidden_wheel_paths():
            candidate = build_lib / relative
            if candidate.exists():
                candidate.unlink()
        for prefix in _forbidden_wheel_prefixes():
            directory = build_lib / prefix
            if directory.exists():
                shutil.rmtree(directory)


def _forbidden_wheel_paths() -> frozenset[Path]:
    return frozenset(
        {
            Path("src/legacy_arb_bot.py"),
            Path("src/execution/live_control.py"),
            Path("src/execution/shadow.py"),
        }
    )


def _forbidden_wheel_prefixes() -> tuple[Path, ...]:
    return (
        Path("src/ingest"),
        Path("src/execution/senders"),
    )


setup(cmdclass={"build_py": ProductionBoundaryBuildPy})
