# providers-wave1-2026-11-13 — Stream G multi-provider quote/build source dossiers

**Scope:** docs + manifest + zero-network verifier only. No `src/` changes, no adapters, no credentials, no live provider calls.

**Owner:** Stream G (agent G) per `docs/roadmap/agent-execution-master-2026-11-13/PARALLEL_EXECUTION_MANDATE.md` §4 Stream G and §7 knowledge-base rules, and `tasks/R13_MULTIPROVIDER_QUOTES_AND_BUILDS.md`.

**Base SHA:** `86be458a87ed3f499cc32ff56426b2866c90422a`
**Retrieval window (UTC):** 2026-11-13T22:20Z through 2026-11-14T00:35Z (single verification session; per-source timestamps in `SOURCE_MANIFEST.json`)

## What this bundle is

Offline, original editorial **contract extracts** (not full upstream page copies) of current official facts for the Wave-1 quote/build providers:

| Provider | Chain(s) | Dossier | Primary flag |
|---|---|---|---|
| Titan | Solana | `TITAN_SOLANA.md` | OFFICIAL_CONTRACT_EXTRACT_ONLY + SDK pin |
| OKX DEX | Solana (+Sui surface noted) | `OKX_DEX_MULTICHAIN.md` | OFFICIAL_CONTRACT_EXTRACT_ONLY |
| OpenOcean | Solana | `OPENOCEAN_SOLANA.md` | OFFICIAL_CONTRACT_EXTRACT_ONLY + typed blockers |
| Rango | Solana + Sui (multi-chain) | `RANGO_MULTICHAIN.md` | OFFICIAL_CONTRACT_EXTRACT_ONLY |
| Aftermath | Sui | `AFTERMATH_SUI.md` | OFFICIAL_CONTRACT_EXTRACT_ONLY + SDK pin |
| Cetus Aggregator | Sui | `CETUS_AGGREGATOR_SUI.md` | OFFICIAL_CONTRACT_EXTRACT_ONLY + SDK pin |
| 7K / Bluefin7K | Sui | `SEVENK_BLUEFIN7K_SUI.md` | OFFICIAL_CONTRACT_EXTRACT_ONLY + SDK pin |
| FlowX | Sui | `FLOWX_SUI.md` | OFFICIAL_CONTRACT_EXTRACT_ONLY + SDK pin |

Jupiter V2 and 0x Solana are already pinned in `docs/integrations/offline/solana-p0/` (Jupiter OpenAPI mirror + 0x contract extract). They are referenced here, never re-pinned. Direct DeepBook is covered by existing GPR-03 Sui lanes.

## Provenance policy

- Only official primary sources were used: provider-owned documentation sites (`.md` variants fetched), provider-owned GitHub repositories / npm registry metadata via authenticated GitHub API (metadata and source constants only), and provider-owned public API pages.
- No credentials exist in this environment; no authenticated provider call was made; no key values appear here (credential/header/query-param **names** only).
- Unknown values are recorded as `UNKNOWN`, never assumed. Nothing here is a live observation; historical repo notes are not treated as current truth.
- Full upstream doc-page copies are deliberately **not** vendored (GitBook page copyright); the extracts are original editorial transcriptions with exact quotes where load-bearing. SDK repositories are pinned by commit/tag metadata; no SDK source is vendored.
- `RAW_OFFICIAL_SNAPSHOT` is therefore not claimed anywhere in this bundle; every entry is `OFFICIAL_CONTRACT_EXTRACT_ONLY` or worse, per the flag taxonomy in PARALLEL_EXECUTION_MANDATE §7.

## Verification

Zero-network verifier (checks manifest completeness + local file hashes; makes no requests):

```bash
python docs/integrations/offline/providers-wave1-2026-11-13/verify_offline_bundle.py
```

It validates: manifest schema completeness per source (canonical URLs, retrieval time, flag, build-output semantics, fee fields, quote-race endpoints, license status), presence of every declared dossier file, SHA-256 of each file against the manifest, and typed completeness of every `BLOCKED_MISSING_PIN` acquisition row.

## Related owners (reference, do not duplicate)

- `docs/integrations/offline/solana-p0/` — Jupiter V2 OpenAPI mirror + 0x extract + `verify_offline_bundle.py` pattern followed here.
- `docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/` — SOURCE_LEDGER.json / CONTRACT_FACTS.json pattern.
- `docs/roadmap/agent-execution-master-2026-11-13/tasks/R13_MULTIPROVIDER_QUOTES_AND_BUILDS.md` — normalization/evidence rules these dossiers feed.
- `config/qualification/din00-source-status.json` — all providers remain disabled by default.
