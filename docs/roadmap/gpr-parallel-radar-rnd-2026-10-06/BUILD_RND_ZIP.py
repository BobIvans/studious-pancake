#!/usr/bin/env python3
"""Build a deterministic review ZIP from the materialized GPR R&D directory."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "GPR_PARALLEL_RADAR_RND_2026-10-06.zip"
INCLUDE = (
    "README.md",
    "CODEX_START_HERE.md",
    "MASTER_CONTEXT.md",
    "MANIFEST.json",
    "QPR03_COMPATIBILITY.md",
    "ARCHITECTURE_CONTRACT.md",
    "IMPLEMENTATION_ROADMAP.md",
    "SOURCE_MATRIX.md",
    "ASSET_PLACEHOLDERS.md",
    "SYMBOLIC_UNIVERSE.md",
    "ANOMALY_TAXONOMY.json",
    "ACCEPTANCE_TESTS.md",
)
with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for name in INCLUDE:
        p = ROOT / name
        if not p.is_file():
            raise SystemExit(f"missing required package file: {name}")
        info = zipfile.ZipInfo(name, date_time=(2026, 10, 6, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        zf.writestr(info, p.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
print(OUT)
