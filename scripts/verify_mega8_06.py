#!/usr/bin/env python3
"""Structural verification for MEGA8-06."""

from __future__ import annotations

import argparse
import ast
import importlib
import inspect
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "mega8_06"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FORBIDDEN_IMPORT_ROOTS = {
    "aiohttp",
    "httpx",
    "requests",
    "solana",
    "solders",
    "subprocess",
    "socket",
}
FORBIDDEN_TOKENS = (
    "send_transaction(",
    "send_raw_transaction(",
    "load_keypair",
    "private_key",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    manifest = importlib.import_module("src.mega8_06.manifest")
    errors: list[str] = []

    if tuple(sorted(manifest.CHILDREN)) != tuple(range(255, 271)):
        errors.append("child range must be PR-255..270")
    if manifest.FUNCTION_COUNT != 64:
        errors.append("function count must be 64")
    if manifest.NF_IDS != tuple(range(705, 769)):
        errors.append("NF range must be 705..768")
    if len(set(manifest.ALL_FUNCTIONS)) != 64:
        errors.append("function names must be unique")

    for child, (_, rows) in sorted(manifest.CHILDREN.items()):
        module = importlib.import_module(f"src.mega8_06.pr{child}")
        for _, name in rows:
            value = getattr(module, name, None)
            if not inspect.isfunction(value):
                errors.append(f"missing function pr{child}.{name}")

    for path in sorted(PACKAGE.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] in FORBIDDEN_IMPORT_ROOTS:
                        errors.append(
                            f"forbidden import {alias.name} in {path.name}"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".", 1)[0] in FORBIDDEN_IMPORT_ROOTS:
                    errors.append(
                        f"forbidden import {node.module} in {path.name}"
                    )
        lowered = text.lower()
        for token in FORBIDDEN_TOKENS:
            if token in lowered:
                errors.append(f"forbidden effect token {token} in {path.name}")

    coverage = json.loads(
        (ROOT / "config" / "mega8_06_coverage.json").read_text()
    )
    if coverage.get("live_enabled") is not False:
        errors.append("live_enabled must remain false")
    if coverage.get("signing_enabled") is not False:
        errors.append("signing_enabled must remain false")
    if coverage.get("submission_enabled") is not False:
        errors.append("submission_enabled must remain false")
    if coverage.get("automatic_capital_increase") is not False:
        errors.append("automatic_capital_increase must remain false")
    if len(coverage.get("children", ())) != 16:
        errors.append("coverage must list 16 children")

    result = {
        "ok": not errors,
        "children": len(manifest.CHILDREN),
        "functions": manifest.FUNCTION_COUNT,
        "nf_first": manifest.NF_IDS[0],
        "nf_last": manifest.NF_IDS[-1],
        "errors": errors,
    }
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(result)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
