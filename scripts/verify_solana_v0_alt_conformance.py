#!/usr/bin/env python3
"""Static fail-closed verifier for Solana v0/ALT and provider boundaries.

The verifier intentionally produces review evidence only.  It never performs
network access and cannot promote live execution.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

READ_METHODS = {"getTransaction", "getBlock", "get_transaction", "get_block"}
LEGACY_JUPITER_PATHS = ("/swap/v1/", "/swap/v2/swap-instructions", "/price/v2")
EXECUTION_DISCOVERY_PROVIDERS = ("okx", "openocean", "odos")


def _python_files() -> list[Path]:
    roots = [ROOT / "src", ROOT / "scripts"]
    return sorted(path for base in roots if base.exists() for path in base.rglob("*.py"))


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _has_version_argument(node: ast.Call) -> bool:
    for keyword in node.keywords:
        if keyword.arg in {"maxSupportedTransactionVersion", "max_supported_transaction_version"}:
            value = keyword.value
            return isinstance(value, ast.Constant) and isinstance(value.value, int) and value.value >= 0
    for arg in node.args:
        if isinstance(arg, ast.Dict):
            for key, value in zip(arg.keys, arg.values):
                if isinstance(key, ast.Constant) and key.value == "maxSupportedTransactionVersion":
                    return isinstance(value, ast.Constant) and isinstance(value.value, int) and value.value >= 0
    return False


def scan_rpc_reads() -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) not in READ_METHODS:
                continue
            if not _has_version_argument(node):
                violations.append(
                    {
                        "code": "SOLANA_VERSIONED_READ_UNBOUND",
                        "path": str(path.relative_to(ROOT)),
                        "line": node.lineno,
                        "call": _call_name(node),
                    }
                )
    return violations


def scan_provider_surfaces() -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    active_paths = [ROOT / "src", ROOT / "config"]
    for base in active_paths:
        if not base.exists():
            continue
        for path in sorted(p for p in base.rglob("*") if p.is_file() and p.suffix in {".py", ".json", ".yaml", ".yml"}):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            lowered = text.lower()
            for legacy in LEGACY_JUPITER_PATHS:
                if legacy in text and "legacy" not in lowered and "quarantine" not in lowered:
                    violations.append(
                        {
                            "code": "JUPITER_LEGACY_ACTIVE_SURFACE",
                            "path": str(path.relative_to(ROOT)),
                            "surface": legacy,
                        }
                    )
            if "execution_provider_allowlist" in lowered:
                for provider in EXECUTION_DISCOVERY_PROVIDERS:
                    if provider in lowered and "discovery_only" not in lowered:
                        violations.append(
                            {
                                "code": "DISCOVERY_PROVIDER_EXECUTION_ESCALATION",
                                "path": str(path.relative_to(ROOT)),
                                "provider": provider,
                            }
                        )
    return violations


def build_report() -> dict[str, Any]:
    rpc = scan_rpc_reads()
    providers = scan_provider_surfaces()
    violations = [*rpc, *providers]
    return {
        "schema_version": "mpr-close-03.solana-provider-conformance.v1",
        "accepted": not violations,
        "live_execution_allowed": False,
        "sender_allowed": False,
        "checks": {
            "versioned_rpc_reads": len(rpc) == 0,
            "provider_execution_boundaries": len(providers) == 0,
        },
        "violations": violations,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = build_report()
    print(json.dumps(report, sort_keys=True, indent=2 if args.json else None))
    return 1 if args.strict and not report["accepted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
