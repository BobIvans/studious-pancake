#!/usr/bin/env python3
"""Structural verifier for MEGA8-01 ownership and effect boundaries."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

from src.mega8_01 import CHILDREN, NF_SYMBOLS, SAFETY_INVARIANTS

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "mega8_01"
FORBIDDEN_IMPORT_ROOTS = {
    "aiohttp",
    "httpx",
    "requests",
    "solana",
    "solders",
    "subprocess",
}
FORBIDDEN_CALL_TOKENS = {
    "send_transaction",
    "sendTransaction",
    "sign_message",
    "sign_transaction",
    "Keypair",
}


def verify() -> dict[str, object]:
    expected_children = tuple(f"PR-{number}" for number in range(151, 163))
    expected_nfs = tuple(f"NF-{number}" for number in range(353, 401))
    actual_children = tuple(CHILDREN)
    actual_nfs = tuple(sorted(NF_SYMBOLS, key=lambda value: int(value.split("-")[1])))
    if actual_children != expected_children:
        raise SystemExit(f"child ownership mismatch: {actual_children}")
    if actual_nfs != expected_nfs:
        raise SystemExit("NF ownership must be exactly NF-353..NF-400")
    if len(set(NF_SYMBOLS.values())) != 48:
        raise SystemExit("MEGA8-01 must expose exactly 48 unique public functions")
    if any(SAFETY_INVARIANTS.values()):
        raise SystemExit("all MEGA8-01 effect authority flags must remain false")

    inspected: list[str] = []
    for path in sorted(PACKAGE.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
                if roots & FORBIDDEN_IMPORT_ROOTS:
                    raise SystemExit(f"forbidden effectful import in {path}: {roots}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in FORBIDDEN_IMPORT_ROOTS:
                    raise SystemExit(f"forbidden effectful import in {path}: {root}")
        for token in FORBIDDEN_CALL_TOKENS:
            if token in text:
                raise SystemExit(f"forbidden effect token in {path}: {token}")
        inspected.append(str(path.relative_to(ROOT)))

    return {
        "children": len(CHILDREN),
        "nfs": len(NF_SYMBOLS),
        "functions": len(set(NF_SYMBOLS.values())),
        "effect_authority": SAFETY_INVARIANTS,
        "inspected": inspected,
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = verify()
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print("MEGA8-01 structural verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
