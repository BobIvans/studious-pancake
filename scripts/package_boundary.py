#!/usr/bin/env python3
"""PR-100 physical production package boundary.

The source tree may retain quarantined legacy modules while parallel hardening PRs
migrate tests and references. The production wheel must not ship those modules.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import shutil

from setuptools.command.build_py import build_py

FORBIDDEN_PRODUCTION_MODULES: frozenset[tuple[str, str]] = frozenset(
    {
        ("src", "legacy_arb_bot"),
        ("src.execution", "live_control"),
        ("src.execution", "shadow"),
    }
)
FORBIDDEN_PRODUCTION_WHEEL_PATHS = frozenset(
    {
        "src/legacy_arb_bot.py",
        "src/execution/live_control.py",
        "src/execution/shadow.py",
    }
)
FORBIDDEN_PRODUCTION_WHEEL_PREFIXES = (
    "src/ingest/",
    "src/execution/senders/",
)
FORBIDDEN_PRODUCTION_PACKAGE_PREFIXES: tuple[str, ...] = tuple(
    prefix.rstrip("/").replace("/", ".")
    for prefix in FORBIDDEN_PRODUCTION_WHEEL_PREFIXES
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


def forbidden_wheel_members(names: Iterable[str]) -> list[str]:
    """Return quarantined members that must not appear in the production wheel."""

    return sorted(
        name
        for name in names
        if name in FORBIDDEN_PRODUCTION_WHEEL_PATHS
        or any(
            name.startswith(prefix)
            for prefix in FORBIDDEN_PRODUCTION_WHEEL_PREFIXES
        )
    )


def _path_from_wheel_member(build_lib: Path, member: str) -> Path:
    return build_lib.joinpath(*member.split("/"))


def prune_quarantined_runtime_members(build_lib: Path) -> tuple[str, ...]:
    """Remove quarantined runtime members from a prepared build output tree."""

    removed: list[str] = []
    for member in sorted(FORBIDDEN_PRODUCTION_WHEEL_PATHS):
        target = _path_from_wheel_member(build_lib, member)
        if target.is_file() or target.is_symlink():
            target.unlink()
            removed.append(member)

    for prefix in FORBIDDEN_PRODUCTION_WHEEL_PREFIXES:
        target = _path_from_wheel_member(build_lib, prefix.rstrip("/"))
        if target.is_dir():
            shutil.rmtree(target)
            removed.append(prefix)
        elif target.exists():
            target.unlink()
            removed.append(prefix)

    return tuple(removed)


class RuntimeBoundaryBuildPy(build_py):
    """setuptools build_py hook that omits quarantined runtime modules."""

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
        prune_quarantined_runtime_members(Path(self.build_lib))
