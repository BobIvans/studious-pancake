#!/usr/bin/env python3
"""Verify semantic CLI ownership and the installed canonical schema registry."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.contracts import SchemaRegistry, SchemaRegistryError  # noqa: E402
from src.kernel import canonical_json_bytes, domain_sha256  # noqa: E402


def build_evidence() -> dict[str, object]:
    errors: list[str] = []
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    target = pyproject["project"]["scripts"]["flashloan-bot"]
    semantic = ROOT / "src/cli_entrypoint.py"
    alias = ROOT / "src/cli_pr189.py"
    alias_source = alias.read_text(encoding="utf-8") if alias.is_file() else ""
    semantic_source = semantic.read_text(encoding="utf-8") if semantic.is_file() else ""
    if not semantic.is_file():
        errors.append("semantic CLI owner is absent")
    if "from src import cli_entrypoint as _impl" not in alias_source:
        errors.append("historical CLI is not a compatibility alias")
    if len(alias_source.splitlines()) > 80:
        errors.append("historical CLI alias still owns substantial logic")
    for forbidden in ("import argparse", "def _inspection_parser", "class _LazyCliModule"):
        if forbidden in alias_source:
            errors.append(f"historical CLI alias owns forbidden logic: {forbidden}")
    for required in ("def _inspection_parser", "def main", "class _LazyCliModule"):
        if required not in semantic_source:
            errors.append(f"semantic CLI owner missing required behavior: {required}")
    if target not in {"src.cli_pr189:main", "src.cli_entrypoint:main"}:
        errors.append(f"unexpected installed target: {target}")
    try:
        registry = SchemaRegistry.load_default()
    except (SchemaRegistryError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"schema registry invalid: {exc}")
        registry_count = 0
        registry_ids: list[str] = []
    else:
        registry_count = len(registry.records)
        registry_ids = sorted(registry.active_ids)
        for required_id in (
            "pr023.runtime-status.v1",
            "failure.reason-code-registry.v1",
            "failure.retry-idempotency-matrix.v1",
            "mpr-td-04.upgrade-security-evidence.v1",
        ):
            try:
                registry.require(required_id)
            except SchemaRegistryError as exc:
                errors.append(str(exc))
    for path in (ROOT / "src/kernel/canonical_json.py", ROOT / "src/kernel/hashing.py"):
        if not path.is_file():
            errors.append(f"canonical kernel file missing: {path.relative_to(ROOT)}")
    sample = canonical_json_bytes({"b": 2, "a": 1})
    if sample != b'{"a":1,"b":2}':
        errors.append("canonical JSON ordering is not deterministic")
    first_hash = domain_sha256(
        domain="mpr-td-01", schema_id="example.v1", payload=sample
    )
    second_hash = domain_sha256(
        domain="mpr-td-01", schema_id="example.v2", payload=sample
    )
    if first_hash == second_hash:
        errors.append("canonical hash is not schema-domain separated")
    registry_path = ROOT / "src/resources/schema_registry.json"
    digest = (
        hashlib.sha256(registry_path.read_bytes()).hexdigest()
        if registry_path.is_file()
        else None
    )
    return {
        "schema_version": "mpr-td-01.canonical-surface-evidence.v1",
        "accepted": not errors,
        "installed_target": target,
        "semantic_owner": "src.cli_entrypoint",
        "compatibility_alias": "src.cli_pr189",
        "alias_line_count": len(alias_source.splitlines()),
        "schema_registry_count": registry_count,
        "schema_registry_ids": registry_ids,
        "schema_registry_sha256": digest,
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
        print("MPR-TD-01 canonical surface:", "PASS" if evidence["accepted"] else "FAIL")
    return 0 if evidence["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
