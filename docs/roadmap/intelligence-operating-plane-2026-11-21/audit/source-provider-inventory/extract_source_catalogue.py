"""OCA-W0C offline source-catalogue extractor.

Reads the two checked-in provider/source catalogues on the pinned checkout and
emits a normalized JSONL inventory. Deterministic: sorted rows, no timestamps,
no network. Run from the repository root:

    python docs/roadmap/intelligence-operating-plane-2026-11-21/audit/\
source-provider-inventory/extract_source_catalogue.py --out source_catalogue.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

MARKET_CATALOG = Path("src/resources/market_source_catalog.json")
PROVIDER_CATALOG = Path(
    "docs/roadmap/r01-r02-live-capital-readers-2026-10-08/PROVIDER_CATALOG.json"
)


def market_rows() -> list[dict[str, Any]]:
    payload = json.loads(MARKET_CATALOG.read_text(encoding="utf-8"))
    rows = []
    for source in sorted(payload["sources"], key=lambda item: item["source_id"]):
        rows.append(
            {
                "record_type": "market_source_catalog_row",
                "source_id": source["source_id"],
                "label": source.get("label"),
                "family": source.get("family"),
                "domains": sorted(source.get("domains") or []),
                "access": source.get("access"),
                "evidence_url_count": len(source.get("evidence_urls") or []),
                "limitation_recorded": bool(source.get("limitation")),
                "enabled": bool(source.get("enabled", False)),
                "catalog_schema": payload.get("schema_version"),
            }
        )
    return rows


def provider_rows() -> list[dict[str, Any]]:
    payload = json.loads(PROVIDER_CATALOG.read_text(encoding="utf-8"))
    rows = []
    for entry in sorted(
        payload["entries"], key=lambda item: str(item.get("provider_id"))
    ):
        rows.append(
            {
                "record_type": "flash_capital_provider_candidate",
                "provider_id": entry.get("provider_id"),
                "chains": sorted(entry.get("chains") or []),
                "capital_class": entry.get("capital_class"),
                "access": entry.get("access"),
                "enabled": bool(entry.get("enabled", False)),
                "catalog_schema": payload.get("schema_version"),
                "catalog_status": payload.get("status"),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = market_rows() + provider_rows()
    lines = [json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows]
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
