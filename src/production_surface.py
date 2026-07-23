"""Production package and image surface authority.

PR-194 moves the sender-free production boundary into one packaged manifest so
source, wheel and container checks use the same allow/deny lists.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import importlib.util
import json
from importlib.resources import files
from typing import Any, cast

MANIFEST_RESOURCE = "production_surface_manifest.json"
SCHEMA_VERSION = "pr194.production-surface.v1"


class ProductionSurfaceError(RuntimeError):
    """Raised when the packaged production surface contract is violated."""


def load_manifest() -> dict[str, Any]:
    """Load and validate the packaged production surface manifest."""

    resource = files("src.resources").joinpath(MANIFEST_RESOURCE)
    manifest = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ProductionSurfaceError("production surface manifest is not an object")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ProductionSurfaceError(
            "production surface manifest schema mismatch: "
            f"{manifest.get('schema_version')!r}"
        )
    return cast(dict[str, Any], manifest)


def _section(manifest: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = manifest.get(name)
    if not isinstance(value, Mapping):
        raise ProductionSurfaceError(f"manifest section {name!r} is missing")
    return cast(Mapping[str, Any], value)


def _string_sequence(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ProductionSurfaceError(f"manifest field {field!r} must be a string list")
    return tuple(value)


def required_wheel_members(manifest: Mapping[str, Any] | None = None) -> frozenset[str]:
    """Return files that must be present in every production wheel."""

    manifest = manifest or load_manifest()
    return frozenset(
        _string_sequence(
            manifest.get("required_wheel_members"),
            field="required_wheel_members",
        )
    )


def required_entrypoints(manifest: Mapping[str, Any] | None = None) -> dict[str, str]:
    """Return the installed console entrypoint contract."""

    manifest = manifest or load_manifest()
    entrypoints = manifest.get("entrypoints")
    if not isinstance(entrypoints, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in entrypoints.items()
    ):
        raise ProductionSurfaceError("manifest field 'entrypoints' must be a string map")
    return dict(cast(Mapping[str, str], entrypoints))


def forbidden_wheel_paths(manifest: Mapping[str, Any] | None = None) -> frozenset[str]:
    """Return exact wheel members that must never be shipped."""

    manifest = manifest or load_manifest()
    forbidden = _section(manifest, "forbidden")
    return frozenset(
        _string_sequence(forbidden.get("module_files"), field="forbidden.module_files")
    )


def forbidden_wheel_prefixes(manifest: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    """Return wheel member prefixes that must never be shipped."""

    manifest = manifest or load_manifest()
    forbidden = _section(manifest, "forbidden")
    return _string_sequence(
        forbidden.get("package_prefixes"),
        field="forbidden.package_prefixes",
    )


def forbidden_import_names(manifest: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    """Return production import names that must not resolve after install."""

    manifest = manifest or load_manifest()
    forbidden = _section(manifest, "forbidden")
    return _string_sequence(
        forbidden.get("import_names"),
        field="forbidden.import_names",
    )


def image_forbidden_imports(manifest: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    """Return development or analytics imports banned from the runtime image."""

    manifest = manifest or load_manifest()
    image = _section(manifest, "image")
    return _string_sequence(
        image.get("forbidden_imports"),
        field="image.forbidden_imports",
    )


def forbidden_wheel_members(
    names: Iterable[str],
    manifest: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return all forbidden wheel members found in *names*."""

    manifest = manifest or load_manifest()
    exact_paths = forbidden_wheel_paths(manifest)
    prefixes = forbidden_wheel_prefixes(manifest)
    return sorted(
        name
        for name in names
        if name in exact_paths or any(name.startswith(prefix) for prefix in prefixes)
    )


def assert_no_forbidden_wheel_members(
    names: Iterable[str],
    manifest: Mapping[str, Any] | None = None,
) -> None:
    """Fail if the wheel contains quarantined production members."""

    forbidden = forbidden_wheel_members(names, manifest)
    if forbidden:
        raise ProductionSurfaceError(
            "wheel contains quarantined production members: " + ", ".join(forbidden)
        )


def importable_forbidden_names(
    names: Iterable[str] | None = None,
) -> list[str]:
    """Return forbidden import names that resolve in the current environment."""

    manifest = load_manifest()
    candidates = tuple(names) if names is not None else (
        forbidden_import_names(manifest) + image_forbidden_imports(manifest)
    )
    return sorted(
        name for name in dict.fromkeys(candidates) if importlib.util.find_spec(name)
    )


def assert_forbidden_imports_unavailable(
    names: Iterable[str] | None = None,
) -> None:
    """Fail if any forbidden import resolves in the current environment."""

    leaked = importable_forbidden_names(names)
    if leaked:
        raise ProductionSurfaceError(
            "forbidden production imports are available: " + ", ".join(leaked)
        )
