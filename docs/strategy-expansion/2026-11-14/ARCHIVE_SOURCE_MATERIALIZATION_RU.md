# Original research archive materialization — required for PAIR-00

## Why this step exists

The repository archive manifest contains provenance and historical Library file IDs, but a CLI coding agent running only from a Git checkout cannot assume it can read ChatGPT Library attachments. The full recovered archive pack is therefore provided separately as:

`STUDIOUS_PANCAKE_ALL_SOURCE_ARCHIVES_2026-11-14.zip`

It contains the eleven original ZIP archives from the OCC/flash-graph context through the first Universal Market Graph, direct-data and market-universe V3, Economic World Graph V4, Source Expansion V4.1, Deep Market Atlas V5, Deep Pair Research V6 and Direct Venue Audit. The ZIP includes its own `ARCHIVE_SHA256_MANIFEST.json` and `README_RU.md`.

## User-side bootstrap

Download the archive pack and place it in the user's Downloads folder. From the repository root run:

```powershell
$archive = Join-Path $HOME "Downloads\STUDIOUS_PANCAKE_ALL_SOURCE_ARCHIVES_2026-11-14.zip"
$destination = "docs\research-archives\original_sources"
if (-not (Test-Path $archive)) {
    throw "Original source archive bundle missing: $archive"
}
New-Item -ItemType Directory -Force $destination | Out-Null
Expand-Archive -LiteralPath $archive -DestinationPath $destination -Force
Get-ChildItem $destination -Filter *.zip | Get-FileHash -Algorithm SHA256
```

Do not overwrite or modify the original ZIP files after extraction. Keep them as immutable research evidence.

## Agent responsibility

1. Verify all eleven archives against `ARCHIVE_SHA256_MANIFEST.json`.
2. Record which archive files are present, missing or checksum-mismatched.
3. If the original bundle is missing or an archive hash fails, mark the corresponding PAIR-00 source rows `BLOCKED_SOURCE_ARCHIVE_UNAVAILABLE` and continue independent tasks. Do not claim PAIR-00 complete.
4. Parse the exact source files into versioned, machine-readable row-level datasets with their original archive name, internal path, row/candidate ID, original chain, symbol, source evidence and SHA-256.
5. Commit normalized/extracted datasets through a separate reviewed PR. Keep the original archives immutable; do not import all rows as runtime-enabled assets or markets.
6. Maintain source lineage and explicit overlaps. Do not add counts across generations: first 519 → V3 1,147 includes earlier rows; V4 838 includes history and additions; V6 175 is a delta to V5.

## Current known research-only semantics

The first archive's 519 candidate rows have no canonical_a, canonical_b or market_identity fields. V3's 1,147 candidate records also have no canonical asset/pool identity in those fields. V4's 838 pairs are symbolic and canonical_count=0. V6's 175 additional rows explicitly lack exact quotes, verified flash capacity and verified pool liquidity. These source states are not changed by extracting the ZIPs.

**Source archive availability is a prerequisite for exact archive-row reconciliation, not permission to execute any route.**
