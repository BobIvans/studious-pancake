#!/usr/bin/env python3
"""Verify the completed MPR-4X-01 architecture and schema foundation."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.contracts import (  # noqa: E402
    PayloadValidationError,
    get_schema_registry,
)
from src.contracts.reachability import (  # noqa: E402
    classify_module,
    compatibility_aliases,
    load_reachability_manifest,
    module_name_for_path,
)
from src.production_surface import load_manifest, required_wheel_members  # noqa: E402
from src.release import ReleaseGenerationIdentity  # noqa: E402


def _module_path(module: str) -> Path | None:
    relative = Path(*module.split("."))
    module_file = ROOT / f"{relative}.py"
    package_file = ROOT / relative / "__init__.py"
    if module_file.is_file():
        return module_file
    if package_file.is_file():
        return package_file
    return None


def _definition_owners(name: str, *, kind: type[ast.AST]) -> list[str]:
    owners: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(
                path.read_text(encoding="utf-8"),
                filename=str(path),
            )
        except (OSError, UnicodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, kind) and getattr(node, "name", None) == name:
                owners.append(path.relative_to(ROOT).as_posix())
    return owners


def _sample_release_payload() -> dict[str, object]:
    digest = "a" * 64
    return {
        "schema_id": "release-generation-identity.v1",
        "source_sha": "b" * 40,
        "wheel_sha256": digest,
        "image_digest": f"sha256:{digest}",
        "schema_registry_sha256": digest,
        "config_identity": "mpr-4x-01-verification",
        "provider_registry_sha256": digest,
        "capability_manifest_sha256": digest,
        "production_surface_sha256": digest,
        "runtime_authority_sha256": digest,
        "dependency_lock_sha256": digest,
        "migration_set_sha256": digest,
    }


def build_evidence() -> dict[str, Any]:
    errors: list[str] = []
    registry = get_schema_registry()
    reachability = load_reachability_manifest()

    required_schema_ids = {
        "release-generation-identity.v1",
        "mpr-4x-01.architecture-reachability.v1",
        "pr194.production-surface.v1",
        "failure.reason-code-registry.v1",
        "failure.retry-idempotency-matrix.v1",
        "mpr-td-04.upgrade-security-evidence.v1",
    }
    missing_schema_ids = sorted(required_schema_ids - registry.active_ids)
    if missing_schema_ids:
        errors.append(f"required schema IDs are not active: {missing_schema_ids!r}")

    owner_missing: list[str] = []
    for record in registry.records:
        if record.status == "retired":
            continue
        if _module_path(record.owner_module) is None:
            owner_missing.append(f"{record.schema_id}:{record.owner_module}")
    if owner_missing:
        errors.append(f"registered schema owners are missing: {owner_missing!r}")

    release_payload = _sample_release_payload()
    release_bytes = registry.validate_payload(
        "release-generation-identity.v1",
        release_payload,
    )
    first_digest = registry.payload_digest(
        schema_id="release-generation-identity.v1",
        payload=release_payload,
        domain="release-generation",
    )
    second_digest = registry.payload_digest(
        schema_id="release-generation-identity.v1",
        payload=release_payload,
        domain="release-generation",
    )
    if first_digest != second_digest or not release_bytes:
        errors.append("release identity validation or digest is not deterministic")

    invalid_payload = dict(release_payload)
    invalid_payload["unexpected"] = True
    try:
        registry.validate_payload(
            "release-generation-identity.v1",
            invalid_payload,
        )
    except PayloadValidationError:
        unknown_field_rejected = True
    else:
        unknown_field_rejected = False
        errors.append("release identity accepted an unknown field")

    identity = ReleaseGenerationIdentity(
        source_sha=str(release_payload["source_sha"]),
        wheel_sha256=str(release_payload["wheel_sha256"]),
        image_digest=str(release_payload["image_digest"]),
        schema_registry_sha256=str(release_payload["schema_registry_sha256"]),
        config_identity=str(release_payload["config_identity"]),
        provider_registry_sha256=str(release_payload["provider_registry_sha256"]),
        capability_manifest_sha256=str(release_payload["capability_manifest_sha256"]),
        production_surface_sha256=str(release_payload["production_surface_sha256"]),
        runtime_authority_sha256=str(release_payload["runtime_authority_sha256"]),
        dependency_lock_sha256=str(release_payload["dependency_lock_sha256"]),
        migration_set_sha256=str(release_payload["migration_set_sha256"]),
    )
    if identity.generation_id != first_digest:
        errors.append("release identity bypasses canonical registry hashing")

    schema_owners = _definition_owners(
        "SchemaRegistry",
        kind=ast.ClassDef,
    )
    if schema_owners != ["src/contracts/registry.py"]:
        errors.append(f"SchemaRegistry has competing source owners: {schema_owners!r}")
    canonical_json_owners = _definition_owners(
        "canonical_json_bytes",
        kind=ast.FunctionDef,
    )
    if canonical_json_owners != ["src/kernel/canonical_json.py"]:
        errors.append(
            "canonical_json_bytes has competing source owners: "
            f"{canonical_json_owners!r}"
        )

    source_modules: dict[str, str] = {}
    for path in sorted((ROOT / "src").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(ROOT).as_posix()
        module = module_name_for_path(relative)
        source_modules[module] = classify_module(module, reachability)
    classification_counts = Counter(source_modules.values())
    if not source_modules:
        errors.append("no installed source modules were classified")

    alias_results: list[dict[str, object]] = []
    for alias in compatibility_aliases(reachability):
        module = str(alias["module"])
        target = str(alias["target"])
        max_lines = int(alias["max_lines"])
        path = _module_path(module)
        target_spec = importlib.util.find_spec(target)
        if path is None:
            errors.append(f"compatibility alias is missing: {module}")
            continue
        source = path.read_text(encoding="utf-8")
        line_count = len(source.splitlines())
        target_marker = target.rsplit(".", 1)[-1]
        accepted = line_count <= max_lines and target_marker in source
        if target_spec is None:
            accepted = False
            errors.append(f"compatibility target is not importable: {target}")
        if not accepted:
            errors.append(
                f"compatibility alias is not thin: {module} "
                f"lines={line_count} limit={max_lines}"
            )
        alias_results.append(
            {
                "module": module,
                "target": target,
                "line_count": line_count,
                "accepted": accepted,
            }
        )

    surface = load_manifest()
    wheel_members = required_wheel_members(surface)
    required_foundation_members = {
        "src/contracts/__init__.py",
        "src/contracts/registry.py",
        "src/contracts/reachability.py",
        "src/release/identity.py",
        "src/resources/schema_registry.json",
        "src/resources/architecture_reachability.json",
    }
    missing_wheel_members = sorted(required_foundation_members - wheel_members)
    if missing_wheel_members:
        errors.append(
            "production surface omits MPR-4X-01 wheel members: "
            f"{missing_wheel_members!r}"
        )

    return {
        "schema_version": "mpr-4x-01.foundation-evidence.v1",
        "accepted": not errors,
        "registry_digest": registry.registry_digest,
        "registered_schema_count": len(registry.records),
        "active_schema_count": len(registry.active_ids),
        "release_identity_digest": identity.generation_id,
        "release_unknown_field_rejected": unknown_field_rejected,
        "schema_registry_source_owners": schema_owners,
        "canonical_json_source_owners": canonical_json_owners,
        "classified_module_count": len(source_modules),
        "classification_counts": dict(sorted(classification_counts.items())),
        "compatibility_aliases": alias_results,
        "missing_wheel_members": missing_wheel_members,
        "sender_free": True,
        "production_ready": False,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    evidence = build_evidence()
    if args.as_json:
        print(json.dumps(evidence, indent=2, sort_keys=True))
    else:
        print(
            "MPR-4X-01 foundation:",
            "PASS" if evidence["accepted"] else "FAIL",
        )
    return 0 if evidence["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
