#!/usr/bin/env python3
"""Static/materialized closure gate for the four aggregated MPR-RP workstreams."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCHEMA = "mpr-rp.runtime-platform-closure.v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _attribute_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _is_os_environ_target(node: ast.AST) -> bool:
    if isinstance(node, ast.Subscript):
        return _attribute_name(node.value) == "os.environ"
    if isinstance(node, (ast.Tuple, ast.List)):
        return any(_is_os_environ_target(item) for item in node.elts)
    return _attribute_name(node) == "os.environ"


def _ambient_state_violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
            targets: list[ast.AST]
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.Delete):
                targets = list(node.targets)
            else:
                targets = [node.target]
            if any(_is_os_environ_target(target) for target in targets):
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}:ENV_MUTATION"
                )
        if isinstance(node, ast.Call):
            called = _attribute_name(node.func)
            if called in {
                "os.environ.update",
                "os.environ.setdefault",
                "os.environ.pop",
                "os.environ.clear",
                "os.environ.__setitem__",
                "os.putenv",
            }:
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}:ENV_MUTATION_CALL"
                )
            if called in {"dotenv.load_dotenv", "load_dotenv"}:
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}:IMPORT_TIME_DOTENV"
                )
    return violations


def verify() -> dict[str, Any]:
    blockers: list[str] = []
    policy_pairs = (
        (
            ROOT / "config/supported_runtime_platforms.json",
            ROOT / "src/resources/supported_runtime_platforms.json",
        ),
        (
            ROOT / "config/command_capabilities.json",
            ROOT / "src/resources/command_capabilities.json",
        ),
    )
    policy_hashes: dict[str, str] = {}
    for source, packaged in policy_pairs:
        if not source.is_file() or not packaged.is_file():
            blockers.append(f"POLICY_MISSING:{source.name}")
            continue
        if source.read_bytes() != packaged.read_bytes():
            blockers.append(f"PACKAGED_POLICY_DRIFT:{source.name}")
        policy_hashes[source.name] = _sha256(source)
        json.loads(source.read_text(encoding="utf-8"))

    scanned = (
        ROOT / "src/cli_entrypoint.py",
        ROOT / "src/cli.py",
        ROOT / "src/container_runtime.py",
        ROOT / "scripts/manage_webhooks.py",
        ROOT / "scripts/setup_helius_webhook.py",
    )
    for path in scanned:
        blockers.extend(_ambient_state_violations(path))
        text = path.read_text(encoding="utf-8")
        if path.parent.name == "scripts" and "src.ingest" in text:
            blockers.append(f"SOURCE_ONLY_OPERATIONAL_IMPORT:{path.name}")

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if (
        'flashloan-external-resources = "src.external_resources.cli:main"'
        not in pyproject
    ):
        blockers.append("INSTALLED_EXTERNAL_RESOURCE_ENTRYPOINT_MISSING")

    from src.runtime.command_capabilities import CommandCapabilityManifest

    manifest = CommandCapabilityManifest.load()
    required_commands = {
        "flashloan-bot",
        "flashloan-bot-healthcheck",
        "flashloan-checks",
        "flashloan-contracts",
        "flashloan-release-evidence",
        "flashloan-external-resources",
    }
    missing_commands = sorted(required_commands - set(manifest.commands))
    blockers.extend(f"COMMAND_MANIFEST_MISSING:{item}" for item in missing_commands)
    status_admission = manifest.evaluate("flashloan-bot.status")
    blockers.extend(status_admission.blockers)

    return {
        "schema_version": SCHEMA,
        "accepted": not blockers,
        "blockers": blockers,
        "policy_hashes": policy_hashes,
        "command_manifest_sha256": manifest.manifest_sha256,
        "status_closure_sha256": status_admission.closure_sha256,
        "scanned_files": [str(path.relative_to(ROOT)) for path in scanned],
    }


def main() -> int:
    payload = verify()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
