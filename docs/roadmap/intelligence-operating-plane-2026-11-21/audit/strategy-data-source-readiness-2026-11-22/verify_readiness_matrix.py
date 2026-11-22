"""Zero-network verifier for the OCA readiness audit matrix.

Checks schema, state-ladder vocabulary, referenced paths/tests existence on
the pinned checkout, absence of live-capability claims, and mode vocabulary.
Run from the repository root:

    python docs/roadmap/intelligence-operating-plane-2026-11-21/audit/\
strategy-data-source-readiness-2026-11-22/verify_readiness_matrix.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MATRIX = Path(__file__).resolve().parent / "READINESS_MATRIX.json"
STATES = {"DECLARED", "DOCUMENTED", "IMPLEMENTED", "TESTED", "CAPTURED", "RUNTIME_OBSERVED"}
MODES = {"STREAMING", "POLL_ONLY", "ONE_SHOT", "UNAVAILABLE"}
ROOT = Path.cwd()


def main() -> int:
    payload = json.loads(MATRIX.read_text(encoding="utf-8"))
    errors: list[str] = []
    if payload["base_main_sha"] != "0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54":
        errors.append("base_main_sha mismatch")
    forbidden = ("LIVE", "live capability proven", "capacity proven")
    for group in ("strategy_rows", "capital_rows"):
        for row in payload[group]:
            unknown_states = set(row["states"]) - STATES
            if unknown_states:
                errors.append(f"{row.get('strategy_id', row.get('capital_id'))}: unknown states {unknown_states}")
            if row["states"].get("RUNTIME_OBSERVED"):
                errors.append(f"{row}: RUNTIME_OBSERVED true requires W10-verified producers (audit forbids)")
            if row.get("source_mode") not in MODES:
                errors.append(f"{row}: bad source_mode {row.get('source_mode')}")
            text = json.dumps(row).lower()
            for phrase in forbidden:
                if phrase in text and "never" not in text and "hard-denied" not in text:
                    errors.append(f"{row}: potential live-capability claim: {phrase}")
            for ref in row.get("support_paths", []) + [row["path"]]:
                if not (ROOT / ref).exists():
                    errors.append(f"{row}: missing path {ref}")
            for test in row.get("tests", []):
                if not (ROOT / test).exists():
                    errors.append(f"{row}: missing test {test}")
    catalog = payload["provider_catalog_refs"]
    for ref in (catalog["market_sources"]["path"], catalog["flash_capital_candidates"]["path"]):
        if not (ROOT / ref).exists():
            errors.append(f"missing catalog {ref}")
    if errors:
        print("FAIL")
        for error in errors:
            print(" -", error)
        return 1
    print("readiness matrix verification OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
