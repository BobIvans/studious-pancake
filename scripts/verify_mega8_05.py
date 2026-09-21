#!/usr/bin/env python3
"""Structural verifier for MEGA8-05 / PR-239..254 / NF-641..704."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COVERAGE = ROOT / "release_artifacts/mega8/MEGA8-05/coverage.json"
EXPECTED_CHILDREN = tuple(f"PR-{number}" for number in range(239, 255))
EXPECTED_NF = tuple(f"NF-{number}" for number in range(641, 705))
FORBIDDEN_IMPORT_ROOTS = {
    "aiohttp",
    "requests",
    "socket",
    "subprocess",
    "solana",
    "solders",
}
FORBIDDEN_PUBLIC_FUNCTIONS = {
    "sign",
    "submit",
    "send_transaction",
    "transfer_funds",
}


class VerificationError(RuntimeError):
    pass


def _load() -> dict[str, Any]:
    return json.loads(COVERAGE.read_text(encoding="utf-8"))


def _public_functions(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return tuple(
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    )


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def verify() -> dict[str, Any]:
    coverage = _load()
    failures: list[str] = []

    if coverage.get("schema") != "mega8-05.research-factory-coverage.v1":
        failures.append("schema")
    if coverage.get("mega_id") != "MEGA8-05":
        failures.append("mega_id")
    if coverage.get("primary_nf_count") != 64:
        failures.append("primary_nf_count")
    if coverage.get("implementation_status") != "IMPLEMENTED_OFFLINE":
        failures.append("implementation_status")
    if coverage.get("operational_status") != "BLOCKED_EXTERNAL_EVIDENCE":
        failures.append("operational_status")
    if coverage.get("activation_status") != "DEFAULT_OFF":
        failures.append("activation_status")

    boundary = coverage.get("effect_boundary", {})
    if any(bool(value) for value in boundary.values()):
        failures.append("effect_boundary")

    source_reuse = coverage.get("source_reuse", {})
    if source_reuse.get("copied_external_source") is not False:
        failures.append("source_copy")
    if source_reuse.get("generated_external_code_executed") is not False:
        failures.append("generated_code_execution")
    if source_reuse.get("unknown_license_allows_copy") is not False:
        failures.append("unknown_license_policy")

    children = coverage.get("children", [])
    child_ids = tuple(child.get("child_id") for child in children)
    if child_ids != EXPECTED_CHILDREN:
        failures.append("child_ids")

    nf_ids = tuple(nf_id for child in children for nf_id in child.get("nf_ids", []))
    if nf_ids != EXPECTED_NF or len(set(nf_ids)) != 64:
        failures.append("nf_ids")

    seen_functions: list[str] = []
    for child in children:
        owner_path = ROOT / str(child.get("owner_path", ""))
        test_path = ROOT / str(child.get("test_path", ""))
        if not owner_path.is_file():
            failures.append(f"missing-owner:{child.get('child_id')}")
            continue
        if not test_path.is_file():
            failures.append(f"missing-test:{child.get('child_id')}")
        actual_functions = _public_functions(owner_path)
        declared_functions = tuple(child.get("functions", []))
        if actual_functions != declared_functions:
            failures.append(f"function-map:{child.get('child_id')}")
        if len(actual_functions) != 4:
            failures.append(f"function-count:{child.get('child_id')}")
        seen_functions.extend(actual_functions)
        forbidden_imports = _imports(owner_path) & FORBIDDEN_IMPORT_ROOTS
        if forbidden_imports:
            failures.append(
                f"effectful-import:{child.get('child_id')}:{sorted(forbidden_imports)}"
            )

    if len(seen_functions) != 64 or len(set(seen_functions)) != 64:
        failures.append("public-function-total")
    if FORBIDDEN_PUBLIC_FUNCTIONS & set(seen_functions):
        failures.append("effectful-public-function")

    base_path = ROOT / "src/research/mega8_05/base.py"
    init_path = ROOT / "src/research/mega8_05/__init__.py"
    if not base_path.is_file() or not init_path.is_file():
        failures.append("package-scaffold")

    blockers = coverage.get("residual_blockers", [])
    required_blockers = {
        "EXTERNAL_UPSTREAM_RELEASE_LICENSE_AND_CONFORMANCE_EVIDENCE_NOT_BUNDLED",
        "NO_LIVE_OR_CAPITAL_PROMOTION_AUTHORIZED",
    }
    if not isinstance(blockers, list) or not required_blockers.issubset(set(blockers)):
        failures.append("residual_blockers")

    result = {
        "schema": "mega8-05.verification-result.v1",
        "ok": not failures,
        "failures": failures,
        "children": len(children),
        "primary_nf": len(nf_ids),
        "public_functions": len(seen_functions),
        "default_off": coverage.get("activation_status") == "DEFAULT_OFF",
        "operational_status": coverage.get("operational_status"),
    }
    if failures:
        raise VerificationError(json.dumps(result, sort_keys=True))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = verify()
    except VerificationError as exc:
        if args.json:
            print(str(exc))
        else:
            print(f"FAIL: {exc}")
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print("PASS: MEGA8-05 structural closure verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
