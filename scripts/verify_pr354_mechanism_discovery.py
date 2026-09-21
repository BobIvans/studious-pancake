#!/usr/bin/env python3
"""Structural verifier for PR-354 mechanism discovery."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

from src.mechanism_discovery.manifest import (
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

REQUIRED_ARTIFACTS = (
    "docs/roadmap/pr354_non_duplication.md",
    "docs/mechanism_discovery/architecture.md",
    "docs/mechanism_discovery/function_registry_nf1089_1184.md",
    "docs/mechanism_discovery/source_provenance.json",
    "docs/mechanism_discovery/source_registry.json",
    "docs/mechanism_discovery/hypothesis_registry.json",
    "docs/mechanism_discovery/anomaly_coverage_matrix.md",
    "docs/mechanism_discovery/qualification_matrix.md",
    "docs/mechanism_discovery/mechanism_dossiers/README.md",
)


def verify() -> dict[str, object]:
    errors: list[str] = []

    if FUNCTION_COUNT != 96 or NF_IDS != tuple(range(1089, 1185)):
        errors.append("PR354_NF_MANIFEST_MISMATCH")

    for nf, (package, module_name, symbol) in sorted(NF_TO_SYMBOL.items()):
        module = importlib.import_module(f"src.mechanism_discovery.{module_name}")
        if not callable(getattr(module, symbol, None)):
            errors.append(f"PR354_SYMBOL_MISSING:{nf}:{package}:{symbol}")

    config = json.loads(
        (ROOT / "config/mechanism_discovery.json").read_text(encoding="utf-8")
    )
    configured = config.get("packages", {})
    if set(configured) != set(PACKAGES):
        errors.append("PR354_PACKAGE_CONFIG_MISMATCH")
    for package in PACKAGES:
        row = configured.get(package, {})
        if row.get("state") != "DISABLED" or row.get("live") is not False:
            errors.append(f"PR354_PACKAGE_NOT_DISABLED:{package}")

    boundary = config.get("effect_boundary", {})
    if not boundary or any(value is not False for value in boundary.values()):
        errors.append("PR354_EFFECT_BOUNDARY_UNSAFE")
    if config.get("source_copy_performed") is not False:
        errors.append("PR354_SOURCE_COPY_FLAG_UNSAFE")

    package_dir = ROOT / "src" / "mechanism_discovery"
    for path in package_dir.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_EFFECT_TOKENS:
            if token in source:
                errors.append(f"PR354_FORBIDDEN_EFFECT_TOKEN:{path.name}:{token}")

    for relative in REQUIRED_ARTIFACTS:
        if not (ROOT / relative).is_file():
            errors.append(f"PR354_REQUIRED_ARTIFACT_MISSING:{relative}")

    provenance = json.loads(
        (ROOT / "docs/mechanism_discovery/source_provenance.json").read_text(
            encoding="utf-8"
        )
    )
    if provenance.get("copy_or_port_performed") is not False:
        errors.append("PR354_UNATTESTED_SOURCE_COPY")
    for row in provenance.get("rows", []):
        if row.get("source_copy_allowed") is not False:
            errors.append("PR354_EXTERNAL_COPY_NOT_PINNED")
        if row.get("reuse_mode") != "REFERENCE_ONLY":
            errors.append("PR354_NON_REFERENCE_REUSE_WITHOUT_PIN")

    hypotheses = json.loads(
        (ROOT / "docs/mechanism_discovery/hypothesis_registry.json").read_text(
            encoding="utf-8"
        )
    )
    rows = hypotheses.get("rows", [])
    expected_ids = [f"H-{index:02d}" for index in range(1, 37)]
    if [row.get("id") for row in rows] != expected_ids:
        errors.append("PR354_HYPOTHESIS_REGISTRY_MISMATCH")
    if any(row.get("execution_right") is not False for row in rows):
        errors.append("PR354_HYPOTHESIS_EXECUTION_RIGHT_UNSAFE")

    for relative in (
        "src/mechanism_discovery/operationalize.py",
        "src/mechanism_discovery/deployment_watcher.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        if "canonical_update_anomaly_coverage_registry" not in source:
            errors.append(f"PR354_EVO09_REUSE_MISSING:{relative}")

    evidence_path = ROOT / "release_artifacts/pr354/evidence_manifest.json"
    if evidence_path.exists():
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        if evidence.get("schema_version") != "pr354.evidence.v1":
            errors.append("PR354_EVIDENCE_SCHEMA_MISMATCH")

    return {
        "accepted": not errors,
        "function_count": FUNCTION_COUNT,
        "nf_first": NF_IDS[0],
        "nf_last": NF_IDS[-1],
        "package_count": len(PACKAGES),
        "hypothesis_count": len(rows),
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
