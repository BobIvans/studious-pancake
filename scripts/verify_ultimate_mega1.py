#!/usr/bin/env python3
"""Structural verifier for ULTIMATE-MEGA1 and recovered MEGA8-08 owners."""

from __future__ import annotations

import argparse
import ast
import importlib
import json
from pathlib import Path

from src.mega8_08.manifest import (
    ALL_FUNCTIONS as RESIDUAL_FUNCTIONS,
    CHILDREN as RESIDUAL_CHILDREN,
    FUNCTION_COUNT as RESIDUAL_COUNT,
    NF_IDS as RESIDUAL_NF_IDS,
)
from src.release_gate.agg15_release_handoff import EXPECTED_NF_COUNT
from src.release_gate.ultimate_mega1_closure import (
    CLOSURE_PACKAGES,
    NF_TO_CLOSURE,
    assert_static_closure_partition,
)
from src.ultimate_mega1.manifest import (
    ALL_FUNCTIONS,
    CHILDREN,
    FUNCTION_COUNT,
    NF_IDS,
)

ROOT = Path(__file__).resolve().parents[1]
ULTIMATE_COVERAGE = ROOT / "release_artifacts/ultimate/ULTIMATE-MEGA1/coverage.json"
RESIDUAL_COVERAGE = ROOT / "release_artifacts/mega8/MEGA8-08/coverage.json"
BANNED_IMPORT_ROOTS = {
    "aiohttp",
    "httpx",
    "requests",
    "socket",
    "subprocess",
    "solana",
    "solders",
}
BANNED_IMPORT_PREFIXES = (
    "src.submission",
    "src.live_boundary",
    "isolated_signer_service",
)


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            values.append(node.module)
    return tuple(values)


def _verify_package(
    package: str,
    children: dict[int, tuple[tuple[int, str], ...]],
) -> list[str]:
    errors: list[str] = []
    for child, rows in sorted(children.items()):
        module = importlib.import_module(f"{package}.pr{child}")
        path = Path(module.__file__ or "")
        for _nf, name in rows:
            if not callable(getattr(module, name, None)):
                errors.append(f"missing-symbol:{package}:{child}:{name}")
        for imported in _imports(path):
            root = imported.split(".", 1)[0]
            if root in BANNED_IMPORT_ROOTS or imported.startswith(
                BANNED_IMPORT_PREFIXES
            ):
                errors.append(f"effectful-import:{package}:{child}:{imported}")
    return errors


def verify() -> dict[str, object]:
    errors: list[str] = []

    if tuple(sorted(RESIDUAL_CHILDREN)) != tuple(range(287, 303)):
        errors.append("residual-child-range")
    if RESIDUAL_COUNT != 64:
        errors.append("residual-function-count")
    if RESIDUAL_NF_IDS != tuple(range(833, 897)):
        errors.append("residual-nf-range")
    if len(set(RESIDUAL_FUNCTIONS)) != 64:
        errors.append("residual-duplicate-functions")

    if tuple(sorted(CHILDREN)) != tuple(range(303, 327)):
        errors.append("ultimate-child-range")
    if FUNCTION_COUNT != 120:
        errors.append("ultimate-function-count")
    if NF_IDS != tuple(range(897, 1017)):
        errors.append("ultimate-nf-range")
    if len(set(ALL_FUNCTIONS)) != 120:
        errors.append("ultimate-duplicate-functions")

    errors.extend(_verify_package("src.mega8_08", RESIDUAL_CHILDREN))
    errors.extend(_verify_package("src.ultimate_mega1", CHILDREN))

    try:
        assert_static_closure_partition()
    except Exception as exc:
        errors.append(f"closure-partition:{exc}")
    if len(CLOSURE_PACKAGES) != 26:
        errors.append("closure-package-count")
    if len(NF_TO_CLOSURE) != 1016:
        errors.append("closure-nf-count")
    if EXPECTED_NF_COUNT != 352:
        errors.append("agg15-predecessor-count")

    ultimate = json.loads(ULTIMATE_COVERAGE.read_text(encoding="utf-8"))
    residual = json.loads(RESIDUAL_COVERAGE.read_text(encoding="utf-8"))
    if ultimate.get("new_nf_range") != [897, 1016]:
        errors.append("ultimate-coverage-new-range")
    if ultimate.get("recovered_predecessor_nf_range") != [833, 896]:
        errors.append("ultimate-coverage-residual-range")
    if ultimate.get("closure_nf_range") != [1, 1016]:
        errors.append("ultimate-coverage-closure-range")
    if residual.get("nf_range") != [833, 896]:
        errors.append("residual-coverage-range")

    for payload_name, payload in (("ultimate", ultimate), ("residual", residual)):
        for field in (
            "production_ready",
            "live_enabled",
            "signer_access",
            "submission_access",
            "network_mutation",
            "automatic_capital_increase",
        ):
            if payload.get(field) is not False:
                errors.append(f"unsafe-flag:{payload_name}:{field}")

    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "residual_children": len(RESIDUAL_CHILDREN),
        "residual_functions": RESIDUAL_COUNT,
        "new_children": len(CHILDREN),
        "new_functions": FUNCTION_COUNT,
        "closure_packages": len(CLOSURE_PACKAGES),
        "closure_nf_count": len(NF_TO_CLOSURE),
        "live_enabled": False,
        "production_ready": False,
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
