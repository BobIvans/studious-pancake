# evm-financing-wave2-2026-11-14 — R09-L2 EVM financing source dossiers (wave 2)

**Scope:** docs + manifest + zero-network verifier only. No `src/` changes, no adapter
code, no credentials, no live RPC calls, no signing/sending/deploying, no capacity
claims. All providers remain disabled.

**Owner:** lane R09-L2 (EVM + Sui dossiers wave-2) per
`docs/roadmap/agent-execution-master-2026-11-13/tasks/R09_MULTICHAIN_AND_DATA_FEEDS.md` (EVM work package).

**Base SHA:** `e2b65c0ceefdc6f9f99cdc0187ff23dc7815acc8` (branch rebased onto
origin/main before push). **Retrieval date:** 2026-11-14 (single verification session;
per-source details in `SOURCE_MANIFEST.json`).

## What this bundle is

Offline, original editorial **contract/doc extracts** (not full upstream copies) for
EVM flash-financing sources, extending merged wave-1 (PR #618, Morpho Blue + Aave V3
deployment pins) with per-deployment flash-loan call-surface pins. Wave-1 files were
not modified; every wave-2 file cites and extends.

| source | chain coverage | dossier | status | headline blockers |
|---|---|---|---|---|
| Aave V3 `flashLoanSimple` | 1 / 10 / 42161 / 8453 (Pool addrs inherited from #618) | `AAVE_V3_FLASHLOAN_SIMPLE_WAVE2.md` | PINNED_CURRENT (source+docs) | MISSING_DEPLOYED_ABI (selectors), live premium, L2 Pool variant, BSL 1.1 |
| Fluid Liquidity layer | 1 / 42161 / 8453 pinned; 10 MISSING_PIN | `FLUID_LIQUIDITY_WAVE2.md` | PARTIAL_PIN | MISSING_PIN public flashloan ABI; OP address; BSL educational-only grant |
| Euler EVK | per-vault (registry MISSING_PIN) | `EULER_EVK_FLASH_WAVE2.md` | PINNED_CURRENT (source+docs) | MISSING_PIN per-vault registry + hook state; BSL 1.1 no-Aug |
| SparkLend | 1 (Pool pinned from official registry) | `SPARK_LEND_PSM3_WAVE2.md` | PINNED_CURRENT (source+docs) | MISSING_PIN live premium + flashLoanEnabled state |
| Spark PSM3 | swap surface | same file | PINNED_CURRENT (negative finding) | not a flash lender — MISSING_PIN typed, QUOTE-surface only |
| EVM callback atomicity note | cross-provider | `EVM_CALLBACK_ATOMICITY_WAVE2.md` | DOCS_REFERENCE_ONLY | selectors MISSING_DEPLOYED_ABI across providers |

Status counts (per-source rows in the table): PINNED_CURRENT = 5 (incl. the PSM3
negative finding and the atomicity note's pinned quotes), PARTIAL_PIN = 1 (Fluid),
MISSING_PIN acquisition rows = 11, BLOCKED rows (license/conformance/capacity) = 8.
Typed blockers live in each dossier and in `SOURCE_MANIFEST.json`.

## Provenance policy

- Only official primary sources: protocol-owned documentation sites, protocol-owned
  GitHub repositories and their machine-readable deployment registries (GitHub API,
  metadata + verbatim constants only).
- Original editorial transcription with load-bearing verbatim quotes; full upstream
  page/file copies are deliberately not vendored.
- `RAW_OFFICIAL_SNAPSHOT` is claimed only for verbatim constants copied from pinned
  official sources (deployment addresses, Solidity signatures, Move struct fields);
  behavior text is `DOCS_REFERENCE_ONLY`.
- Unknown values are typed (`MISSING_PIN`, `MISSING_DEPLOYED_ABI`,
  `BLOCKED_MISSING_PIN`, `BLOCKED_LICENSE_GRANT`, `EXTERNAL_CONFORMANCE_MISSING`),
  never assumed. Capacity is UNKNOWN everywhere: a web/docs pin is NOT capacity proof.

## Verification (zero network)

```bash
"C:/Users/ivans/Downloads/studious-pancake-main (IDE)/studious-pancake/.venv/Scripts/python.exe" -I \
  docs/integrations/offline/evm-financing-wave2-2026-11-14/verify_offline_bundle.py
```

Checks manifest completeness, presence + SHA-256 (CRLF-normalized) of every dossier,
deployment-address format, typed-blocker completeness, and safety invariants
(no enablement, no capacity claims). Recorded verifier output is in the PR.

## Related owners (reference, do not duplicate)

- `docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/` — wave-1 EVM dossiers
  (PR #618): `EVM_PROTOCOL_DOSSIERS.md`, `SOURCE_LEDGER.json`, `verify_bundle.py`.
- `docs/integrations/offline/providers-wave1-2026-11-13/` — PR #621 quote-routing
  dossiers (Aftermath/Cetus-agg/FlowX are QUOTE surfaces there).
- `docs/integrations/offline/sui-market-wave2-2026-11-14/` — Sui wave-2 (same PR).
- `src/multichain/evm_financing.py` — canonical runtime owner of EVM flash obligation
  math (read-only context for this lane; untouched).
- `src/resources/multichain_capabilities.json` — capability rows stay
  `implemented_offline` with blockers; entries would be promoted only after
  deployment + capacity proof (R-02 bounded read + R-05 fork simulation). This wave
  does NOT edit that file.
