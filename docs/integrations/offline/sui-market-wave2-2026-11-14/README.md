# sui-market-wave2-2026-11-14 — R09-L2 Sui market source dossiers (wave 2)

**Scope:** docs + manifest + zero-network verifier only. No `src/` changes, no adapter
code, no credentials, no live RPC/GraphQL/gRPC calls, no signing/sending, no capacity
claims. All providers remain disabled.

**Owner:** lane R09-L2 (EVM + Sui dossiers wave-2) per
`docs/roadmap/agent-execution-master-2026-11-13/tasks/R09_MULTICHAIN_AND_DATA_FEEDS.md` (Sui work package).

**Base SHA:** `e2b65c0ceefdc6f9f99cdc0187ff23dc7815acc8` (branch rebased onto
origin/main before push). **Retrieval date:** 2026-11-14 (single verification session;
per-source details in `SOURCE_MANIFEST.json`).

## What this bundle is

Offline, original editorial **contract/doc extracts** (not full upstream copies) for
Sui market-structure sources: pool object schemas, official package/object IDs, the
DeepBook V3 flash-loan status, and the PTB atomicity model. Additive to the R01/R02
Sui ledger rows and to PR #621's QUOTE-routing dossiers (Aftermath/Cetus-agg/FlowX
SDK surfaces stay owned there).

| source | dossier | status | headline blockers |
|---|---|---|---|
| Cetus CLMM pool schema + mainnet IDs | `CETUS_CLMM_POOL_WAVE2.md` | PINNED_CURRENT (Move struct + SDK config) | SDK config stale 2025-02-28; no flash lender (MISSING_PIN); capacity UNKNOWN |
| Aftermath router on-chain packages | `AFTERMATH_ROUTER_WAVE2.md` | PINNED_CURRENT (docs contracts page) | per-pool fee state; no flash lender (MISSING_PIN) |
| FlowX aggregator on-chain | `FLOWX_AGGREGATOR_WAVE2.md` | PARTIAL_PIN | aggregator package MISSING_PIN; AMM/ZAPPER anchors only; no flash lender |
| DeepBook V3 flash loans | `DEEPBOOK_V3_FLASH_WAVE2.md` | PINNED_CURRENT (docs live + repo Published.toml v9) | live per-pool capacity UNKNOWN; pool registry pin |
| Sui PTB atomicity note | `SUI_PTB_ATOMICITY_WAVE2.md` | DOCS_REFERENCE_ONLY (official citations) | none new (per-source blockers) |

Status counts (per-source rows): PINNED_CURRENT = 4, PARTIAL_PIN = 1 (FlowX),
MISSING_PIN acquisition rows = 8, BLOCKED rows (capacity/license/conformance) = 10.
Typed blockers live in each dossier and in `SOURCE_MANIFEST.json`.

Headline correction: search-snippet noise claims a DeepBook mainnet package
`0x2c8d552b...`; the official `Published.toml` (MystenLabs/deepbookv3) pins
`published-at 0xbca0cef...fe8` (original `0x2c8d603...809`, version 9). Snippets are
not evidence.

## Provenance policy

- Only official primary sources: protocol-owned docs sites (`.md` variants),
  protocol/Mysten-owned GitHub repos via authenticated GitHub API (metadata +
  verbatim constants), official Sui docs.
- Original editorial transcription with load-bearing verbatim quotes; full upstream
  page/file copies deliberately not vendored.
- `RAW_OFFICIAL_SNAPSHOT` claimed only for verbatim constants (Move struct fields,
  package/object IDs, Move function signatures); behavior text is
  `DOCS_REFERENCE_ONLY`.
- Unknown is typed (`MISSING_PIN`, `BLOCKED_MISSING_PIN`,
  `EXTERNAL_CONFORMANCE_MISSING`), never assumed; capacity UNKNOWN everywhere.

## Verification (zero network)

```bash
"C:/Users/ivans/Downloads/studious-pancake-main (IDE)/studious-pancake/.venv/Scripts/python.exe" -I \
  docs/integrations/offline/sui-market-wave2-2026-11-14/verify_offline_bundle.py
```

Checks manifest completeness, presence + SHA-256 (CRLF-normalized) of every dossier,
0x64-hex object/package ID format, typed-blocker completeness, and safety invariants.
Recorded verifier output is in the PR.

## Related owners (reference, do not duplicate)

- `docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/` — Sui ledger rows
  (NAVI/DeepBook/Scallop/Bucket/Cetus/Suilend) + `SOURCE_LEDGER.json`.
- `docs/integrations/offline/providers-wave1-2026-11-13/` — PR #621 QUOTE-routing
  dossiers (sibling surfaces for Aftermath/Cetus-agg/FlowX).
- `docs/integrations/offline/evm-financing-wave2-2026-11-14/` — EVM wave-2 (same PR;
  domain-isolated counterpart note for callbacks vs PTBs).
- `src/multichain/sui.py` — canonical runtime model of PTB/hot-potato obligations and
  the read-only NAVI capacity reader (read-only context; untouched).
- `src/resources/multichain_capabilities.json` — Sui capability rows stay
  `implemented_offline`; promotion only after deployment + capacity proof.
