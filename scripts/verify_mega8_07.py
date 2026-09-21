#!/usr/bin/env python3
"""Structural verifier for MEGA8-07."""

from __future__ import annotations

import argparse
import ast
import importlib
import json
from pathlib import Path

from src.mega8_07.manifest import ALL_FUNCTIONS, CHILDREN, FUNCTION_COUNT, NF_IDS

COVERAGE = Path("release_artifacts/mega8/MEGA8-07/coverage.json")
BANNED_IMPORT_PREFIXES = (
    "aiohttp",
    "requests",
    "httpx",
    "solana.rpc",
    "solders.keypair",
    "subprocess",
    "src.submission",
)


def _module_imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return tuple(imports)


def verify() -> dict[str, object]:
    coverage = json.loads(COVERAGE.read_text(encoding="utf-8"))
    errors: list[str] = []

    if tuple(CHILDREN) != tuple(range(271, 287)):
        errors.append("child-range")
    if FUNCTION_COUNT != 64:
        errors.append("function-count")
    if NF_IDS != tuple(range(769, 833)):
        errors.append("nf-range")
    if len(set(ALL_FUNCTIONS)) != 64:
        errors.append("duplicate-functions")

    observed: set[str] = set()
    for child, (_, rows) in CHILDREN.items():
        module = importlib.import_module(f"src.mega8_07.pr{child}")
        path = Path(module.__file__ or "")
        for _, name in rows:
            if not callable(getattr(module, name, None)):
                errors.append(f"missing-symbol:{child}:{name}")
            observed.add(name)
        for imported in _module_imports(path):
            if imported.startswith(BANNED_IMPORT_PREFIXES):
                errors.append(f"effectful-import:{child}:{imported}")

    if observed != set(ALL_FUNCTIONS):
        errors.append("ownership-mismatch")
    if coverage.get("roadmap_children") != list(range(271, 287)):
        errors.append("coverage-child-range")
    if coverage.get("nf_range") != [769, 832]:
        errors.append("coverage-nf-range")
    if len(coverage.get("children", [])) != 16:
        errors.append("coverage-child-count")
    for flag in (
        "production_ready",
        "live_enabled",
        "signer_access",
        "submission_access",
        "network_mutation",
        "automatic_capital_increase",
    ):
        if coverage.get(flag) is not False:
            errors.append(f"unsafe-flag:{flag}")
    if coverage.get("operational_status") != "BLOCKED_EXTERNAL_AND_PROMOTION_EVIDENCE":
        errors.append("dependency-truth")
    if coverage.get("implementation_status") != "IMPLEMENTED_OFFLINE":
        errors.append("implementation-status")

    return {
        "status": "PASS" if not errors else "FAIL",
        "children": len(CHILDREN),
        "functions": FUNCTION_COUNT,
        "nf_first": NF_IDS[0],
        "nf_last": NF_IDS[-1],
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify()
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(result)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
