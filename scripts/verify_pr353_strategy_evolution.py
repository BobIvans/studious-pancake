#!/usr/bin/env python3
"""Structural verifier for PR-353 strategy evolution."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from src.strategy_evolution.manifest import (
    FUNCTION_COUNT,
    NF_IDS,
    NF_TO_SYMBOL,
    PACKAGES,
)

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_EFFECT_TOKENS = (
    "from src.submission",
    "import src.submission",
    "isolated_signer_service",
    "from src.live_boundary",
    "import src.live_boundary",
    "send_transaction(",
    "submit_transaction(",
)

REQUIRED_DOCS = (
    "docs/roadmap/pr353_non_duplication.md",
    "docs/strategy_evolution/architecture.md",
    "docs/strategy_evolution/function_registry_nf1017_1088.md",
    "docs/strategy_evolution/source_provenance.json",
    "docs/strategy_evolution/data_source_registry.json",
    "docs/strategy_evolution/anomaly_taxonomy.md",
    "docs/strategy_evolution/coverage_matrix.md",
    "docs/strategy_evolution/qualification_matrix.md",
    "docs/strategy_evolution/runbook_shadow_only.md",
    "docs/strategy_evolution/rollback.md",
    "docs/strategy_evolution/migration.md",
)


def verify() -> dict[str, object]:
    errors: list[str] = []

    if FUNCTION_COUNT != 72 or NF_IDS != tuple(range(1017, 1089)):
        errors.append("PR353_NF_MANIFEST_MISMATCH")

    for nf, (package, module_name, symbol) in sorted(NF_TO_SYMBOL.items()):
        module = importlib.import_module(f"src.strategy_evolution.{module_name}")
        if not callable(getattr(module, symbol, None)):
            errors.append(f"PR353_SYMBOL_MISSING:{nf}:{package}:{symbol}")

    config = json.loads(
        (ROOT / "config/strategy_evolution.json").read_text(encoding="utf-8")
    )
    configured = config.get("packages", {})
    if set(configured) != set(PACKAGES):
        errors.append("PR353_PACKAGE_CONFIG_MISMATCH")
    for package in PACKAGES:
        row = configured.get(package, {})
        if row.get("state") != "DISABLED" or row.get("live") is not False:
            errors.append(f"PR353_PACKAGE_NOT_DISABLED:{package}")

    boundary = config.get("effect_boundary", {})
    forbidden_fields = (
        "signing",
        "submission",
        "relayer",
        "raw_transaction_builder",
        "key_loader",
        "live_permission",
        "auto_promotion",
        "remote_mutation",
    )
    if any(boundary.get(field) is not False for field in forbidden_fields):
        errors.append("PR353_EFFECT_BOUNDARY_UNSAFE")

    package_dir = ROOT / "src" / "strategy_evolution"
    for path in package_dir.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_EFFECT_TOKENS:
            if token in source:
                errors.append(
                    f"PR353_FORBIDDEN_EFFECT_TOKEN:{path.name}:{token}"
                )

    for relative in REQUIRED_DOCS:
        if not (ROOT / relative).is_file():
            errors.append(f"PR353_REQUIRED_DOC_MISSING:{relative}")

    provenance = json.loads(
        (ROOT / "docs/strategy_evolution/source_provenance.json").read_text(
            encoding="utf-8"
        )
    )
    if provenance.get("copy_or_port_performed") is not False:
        errors.append("PR353_UNATTESTED_SOURCE_COPY")
    for row in provenance.get("rows", []):
        if row.get("source_copy_allowed") is not False:
            errors.append("PR353_EXTERNAL_COPY_NOT_PINNED")

    evo09_source = (
        ROOT / "src/strategy_evolution/residual_discovery.py"
    ).read_text(encoding="utf-8")
    if "from src.decision.agg10 import lead_lag_research" not in evo09_source:
        errors.append("PR353_EVO09_CANONICAL_LEAD_LAG_REUSE_MISSING")

    evidence_path = ROOT / "release_artifacts/pr353/evidence_manifest.json"
    if evidence_path.exists():
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        if evidence.get("schema_version") != "pr353.evidence.v1":
            errors.append("PR353_EVIDENCE_SCHEMA_MISMATCH")
        if not evidence.get("implementation_head_sha"):
            errors.append("PR353_EVIDENCE_HEAD_MISSING")

    return {
        "accepted": not errors,
        "function_count": FUNCTION_COUNT,
        "nf_first": NF_IDS[0],
        "nf_last": NF_IDS[-1],
        "package_count": len(PACKAGES),
        "errors": errors,
        "live_enabled": False,
        "signing_enabled": False,
        "submission_enabled": False,
        "auto_promotion_enabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = verify()
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(payload)
    return 0 if payload["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
