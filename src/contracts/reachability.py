"""Machine-readable installed architecture reachability authority."""

from __future__ import annotations

from collections.abc import Mapping
from importlib.resources import files
import json
from pathlib import PurePosixPath
from typing import Any, Final, cast

from src.contracts.registry import get_schema_registry

_REACHABILITY_RESOURCE: Final = "architecture_reachability.json"
_REACHABILITY_SCHEMA_ID: Final = "mpr-4x-01.architecture-reachability.v1"


class ReachabilityError(ValueError):
    """Raised when the architecture reachability manifest is malformed."""


def load_reachability_manifest() -> dict[str, Any]:
    """Load and validate the installed architecture classification manifest."""

    text = (
        files("src.resources")
        .joinpath(_REACHABILITY_RESOURCE)
        .read_text(encoding="utf-8")
    )
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReachabilityError(
            "architecture reachability manifest is not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise ReachabilityError("architecture reachability manifest must be an object")
    get_schema_registry().validate_payload(_REACHABILITY_SCHEMA_ID, value)
    return cast(dict[str, Any], value)


def module_name_for_path(path: str | PurePosixPath) -> str:
    """Convert one source path below the repository root into an import name."""

    source = PurePosixPath(path)
    if source.suffix != ".py":
        raise ReachabilityError(f"not a Python source path: {source}")
    parts = list(source.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    if not parts or parts[0] != "src":
        raise ReachabilityError(f"path is outside the installed src package: {source}")
    return ".".join(parts)


def classify_module(
    module: str,
    manifest: Mapping[str, Any] | None = None,
) -> str:
    """Return the unique architecture classification for an installed module."""

    manifest = manifest or load_reachability_manifest()
    canonical = _string_set(manifest.get("canonical_modules"), "canonical_modules")
    aliases = {
        _required_text(item, "module")
        for item in _mapping_list(
            manifest.get("compatibility_aliases"),
            "compatibility_aliases",
        )
    }
    quarantined = _string_set(
        manifest.get("quarantined_modules"),
        "quarantined_modules",
    )
    if module in canonical:
        return "canonical"
    if module in aliases:
        return "compatibility-alias"
    if any(
        module == prefix or module.startswith(f"{prefix}.") for prefix in quarantined
    ):
        return "quarantined"
    if manifest.get("default_classification") != "installed-support":
        raise ReachabilityError("unsupported default architecture classification")
    return "installed-support"


def compatibility_aliases(
    manifest: Mapping[str, Any] | None = None,
) -> tuple[dict[str, object], ...]:
    """Return validated compatibility-alias declarations."""

    manifest = manifest or load_reachability_manifest()
    aliases: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in _mapping_list(
        manifest.get("compatibility_aliases"),
        "compatibility_aliases",
    ):
        module = _required_text(item, "module")
        target = _required_text(item, "target")
        max_lines = item.get("max_lines")
        if (
            not isinstance(max_lines, int)
            or isinstance(max_lines, bool)
            or max_lines <= 0
        ):
            raise ReachabilityError(
                f"compatibility alias {module} has invalid max_lines"
            )
        if module in seen:
            raise ReachabilityError(f"duplicate compatibility alias: {module}")
        seen.add(module)
        aliases.append(
            {
                "module": module,
                "target": target,
                "max_lines": max_lines,
            }
        )
    return tuple(aliases)


def _mapping_list(
    value: object,
    field: str,
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list):
        raise ReachabilityError(f"{field} must be a list")
    result: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ReachabilityError(f"{field} must contain objects")
        result.append(item)
    return tuple(result)


def _string_set(value: object, field: str) -> frozenset[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ReachabilityError(f"{field} must be a non-empty string list")
    if len(value) != len(set(value)):
        raise ReachabilityError(f"{field} contains duplicates")
    return frozenset(value)


def _required_text(value: Mapping[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise ReachabilityError(f"{field} must be non-empty text")
    return item
