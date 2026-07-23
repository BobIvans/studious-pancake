"""Production package boundary customisations.

PR-087 keeps legacy/quarantined source files in the repository for migration
and forensic review, but prevents them from being emitted into the installed
runtime wheel. PR-194 makes the boundary manifest-driven so source, wheel and
container verification read the same production surface contract.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import shutil
from typing import Any, cast

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py

MANIFEST_PATH = (
    Path(__file__).parent / "src" / "resources" / "production_surface_manifest.json"
)


def _load_manifest() -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise RuntimeError("production surface manifest must be a JSON object")
    if manifest.get("schema_version") != "pr194.production-surface.v1":
        raise RuntimeError("unexpected production surface manifest schema")
    return cast(dict[str, Any], manifest)


def _manifest_string_list(section: str, key: str) -> tuple[str, ...]:
    manifest = _load_manifest()
    value = manifest.get(section)
    if not isinstance(value, dict):
        raise RuntimeError(f"production surface section {section!r} is missing")
    entries = value.get(key)
    if not isinstance(entries, list) or not all(
        isinstance(entry, str) for entry in entries
    ):
        raise RuntimeError(f"production surface field {section}.{key} must be strings")
    return tuple(entries)


def _module_path_to_package_module(relative_path: str) -> tuple[str, str]:
    path = PurePosixPath(relative_path)
    if path.suffix != ".py":
        raise RuntimeError(
            f"forbidden module path is not a Python file: {relative_path}"
        )
    without_suffix = path.with_suffix("")
    package = ".".join(without_suffix.parts[:-1])
    module = without_suffix.name
    if not package or not module:
        raise RuntimeError(f"forbidden module path is malformed: {relative_path}")
    return package, module


def _package_prefix_from_wheel_prefix(prefix: str) -> str:
    stripped = prefix.rstrip("/")
    package = ".".join(PurePosixPath(stripped).parts)
    if not package:
        raise RuntimeError(f"forbidden package prefix is malformed: {prefix}")
    return package


def _forbidden_production_modules() -> frozenset[tuple[str, str]]:
    return frozenset(
        _module_path_to_package_module(path)
        for path in _manifest_string_list("forbidden", "module_files")
    )


def _forbidden_production_package_prefixes() -> tuple[str, ...]:
    return tuple(
        _package_prefix_from_wheel_prefix(prefix)
        for prefix in _manifest_string_list("forbidden", "package_prefixes")
    )


def _is_forbidden_package(package: str) -> bool:
    return any(
        package == prefix or package.startswith(f"{prefix}.")
        for prefix in _forbidden_production_package_prefixes()
    )


def _is_forbidden_module(package: str, module: str) -> bool:
    return (
        _is_forbidden_package(package)
        or (
            package,
            module,
        )
        in _forbidden_production_modules()
    )


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
        Path(path) for path in _manifest_string_list("forbidden", "module_files")
    )


def _forbidden_wheel_prefixes() -> tuple[Path, ...]:
    return tuple(
        Path(prefix)
        for prefix in _manifest_string_list("forbidden", "package_prefixes")
    )


setup(cmdclass={"build_py": ProductionBoundaryBuildPy})
