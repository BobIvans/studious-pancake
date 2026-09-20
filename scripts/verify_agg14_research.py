"""Deterministic static verifier for AGG-14 offline research coverage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

EXPECTED = {f"NF-{number}" for number in range(308, 324)}


def verify(root: Path) -> dict[str, object]:
    coverage_path = root / "config" / "agg14_research_coverage.json"
    payload = json.loads(coverage_path.read_text(encoding="utf-8"))
    rows = payload.get("nf")
    if not isinstance(rows, list):
        raise ValueError("AGG14_COVERAGE_ROWS_MISSING")
    ids = [row.get("id") for row in rows if isinstance(row, dict)]
    if len(ids) != 16 or set(ids) != EXPECTED or len(set(ids)) != len(ids):
        raise ValueError("AGG14_COVERAGE_NOT_EXACT_16_NF")
    for key in ("live_enabled", "signing_enabled", "submission_enabled", "production_ready"):
        if payload.get(key) is not False:
            raise ValueError(f"AGG14_UNSAFE_FLAG:{key}")
    required_files = (
        "src/research/__init__.py",
        "src/research/common.py",
        "src/research/evidence.py",
        "src/research/benchmarks.py",
        "src/research/product.py",
        "src/research/verifiability.py",
        "src/research/promotion.py",
        "tests/test_agg14_research_system.py",
        "docs/agg/agg-14.md",
        "docs/agg/agg-14-upstream.md",
    )
    missing = [path for path in required_files if not (root / path).is_file()]
    if missing:
        raise ValueError("AGG14_REQUIRED_FILES_MISSING:" + ",".join(missing))
    source = "\n".join((root / path).read_text(encoding="utf-8") for path in required_files if path.startswith("src/"))
    forbidden = (
        "sendTransaction(",
        ".send_transaction(",
        "send_raw_transaction(",
        "from src.execution.senders",
        "import src.execution.senders",
        "LIVE_TRADING_ENABLED=true",
    )
    hits = [needle for needle in forbidden if needle in source]
    if hits:
        raise ValueError("AGG14_FORBIDDEN_EFFECT_SURFACE:" + ",".join(hits))
    return {
        "schema": "agg14.verify-result.v1",
        "ok": True,
        "nf_count": len(ids),
        "implementation_status": payload.get("implementation_status"),
        "operational_status": payload.get("operational_status"),
        "unsafe_effects_enabled": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = verify(root)
    print(json.dumps(result, sort_keys=True) if args.json else result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
