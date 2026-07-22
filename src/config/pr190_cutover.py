"""Conflict-safe active cutover for PR-190 configuration seams.

The repository is receiving parallel production-readiness changes.  This module
patches only the configuration ingress/identity callables after the corresponding
active modules load, avoiding replacement of unrelated runtime code.  It adds no
signer, sender, provider call, or live activation path.
"""
from __future__ import annotations

import hashlib
from importlib import resources
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import PathFinder
from importlib.util import spec_from_loader
import sys
from types import ModuleType
from typing import Any

from src.config.canonical import canonical_digest
from src.config.strict_yaml import StrictYamlError, load_strict_yaml, loads_strict_yaml
from src.execution.live_policy import canonical_policy_hash, load_live_policy

_TARGETS = frozenset({"src.config.runtime", "src.execution.live_control"})
_INSTALLED = False


def _patch_runtime(module: ModuleType) -> None:
    def read_yaml(path: Any) -> dict[str, Any]:
        try:
            value = load_strict_yaml(path)
        except (OSError, StrictYamlError) as exc:
            raise module.ConfigurationLoadError(
                f"cannot read configuration file {path}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise module.ConfigurationLoadError("configuration root must be a mapping")
        return value

    def default_payload() -> dict[str, Any]:
        resource = resources.files("src.resources").joinpath("runtime.default.yaml")
        try:
            value = loads_strict_yaml(resource.read_text(encoding="utf-8"))
        except StrictYamlError as exc:
            raise module.ConfigurationLoadError(
                "packaged runtime defaults are invalid"
            ) from exc
        if not isinstance(value, dict):
            raise module.ConfigurationLoadError("packaged runtime defaults are invalid")
        return value

    def safe_display(config: Any) -> dict[str, Any]:
        return config.redacted_dict()

    def identity_payload(config: Any) -> dict[str, Any]:
        return config._fingerprint_dict()

    def runtime_materialization(config: Any) -> dict[str, Any]:
        return config._fingerprint_dict()

    def fingerprint(config: Any) -> str:
        return canonical_digest(
            identity_payload(config),
            domain="flashloan.runtime-config",
            schema_version=config.schema_version,
            environment=config.cluster.name,
        )

    module._read_yaml = read_yaml
    module._default_payload = default_payload
    module.RuntimeConfig.safe_display = safe_display
    module.RuntimeConfig.identity_payload = identity_payload
    module.RuntimeConfig.runtime_materialization = runtime_materialization
    module.RuntimeConfig.fingerprint = fingerprint
    module.PR190_CANONICAL_CONFIG_ACTIVE = True


def _patch_live_control(module: ModuleType) -> None:
    module.load_policy = load_live_policy
    module.canonical_policy_hash = canonical_policy_hash
    module.PR190_CANONICAL_POLICY_ACTIVE = True


def _patch(module: ModuleType) -> None:
    if module.__name__ == "src.config.runtime":
        _patch_runtime(module)
    elif module.__name__ == "src.execution.live_control":
        _patch_live_control(module)


class _CutoverLoader(Loader):
    def __init__(self, wrapped: Loader):
        self.wrapped = wrapped

    def create_module(self, spec: Any) -> ModuleType | None:
        create = getattr(self.wrapped, "create_module", None)
        return create(spec) if create is not None else None

    def exec_module(self, module: ModuleType) -> None:
        self.wrapped.exec_module(module)
        _patch(module)


class _CutoverFinder(MetaPathFinder):
    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        if fullname not in _TARGETS:
            return None
        spec = PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return None
        replacement = spec_from_loader(
            fullname,
            _CutoverLoader(spec.loader),
            origin=spec.origin,
            is_package=spec.submodule_search_locations is not None,
        )
        if replacement is not None:
            replacement.submodule_search_locations = spec.submodule_search_locations
            replacement.cached = spec.cached
            replacement.has_location = spec.has_location
        return replacement


def install_pr190_cutover() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    for name in _TARGETS:
        loaded = sys.modules.get(name)
        if loaded is not None:
            _patch(loaded)
    sys.meta_path.insert(0, _CutoverFinder())


__all__ = ["install_pr190_cutover"]
