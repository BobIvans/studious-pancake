# OCA-W0C — provider/source/strategy extraction and flash-loan data-path inventory

- **Date:** 2026-11-22
- **Lane:** OCA-W0C (PARALLEL_READ_ONLY_AUDIT; WORK_PACKAGE_MATRIX.json, design PR #666 head `6214202b`)
- **Base main SHA:** `0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54`
- **Branch:** `codex/oca-w0c-source-provider-inventory-2026-11-22`
- **Mode:** read-only audit. No network probes, no RPC mutation, no production actions, no code changes outside `docs/roadmap/intelligence-operating-plane-2026-11-21/audit/source-provider-inventory/`.

## 1. Delivered

| Deliverable | Path |
|---|---|
| Source catalogue JSONL (80 normalized rows) | `source_catalogue.jsonl` |
| Deterministic extractor (audit tooling) | `extract_source_catalogue.py` |
| Strategy-provider trace matrix | `strategy_provider_trace_matrix.json` |
| Flashloan data-path dossier | `FLASHLOAN_DATA_PATH_DOSSIER.md` |
| Capability gap report | `CAPABILITY_GAP_REPORT.md` |
| Lane receipt | `../W0C_RECEIPT.json` |

## 2. Source catalogue receipts

- `src/resources/market_source_catalog.json` (`shadow.market-source-catalog.v1`, checked 2026-10-06): **53 rows**, families: router 8, lending-tool 7, amm-tool 9, cex-orderbook 5, reference 9, infrastructure 5, discovery 2, rpc 4, orderbook-tool 4. Access mix: access-not-verified 21, open-source-rpc-or-host-required 18, public-rate-limited 11, free-tier-key-required 3. **0 rows enabled.**
- `PROVIDER_CATALOG.json` (`r02.flashloan-provider-selection.v2`, audited 2026-10-08 at main `103c1379`): **27 flash-capital candidates**, status `RND_ONLY_27_OPTIONS_ALL_DISABLED_NO_LIVE_CAPITAL`. **0 enabled.**
- Normalized output: 80 JSONL rows, deterministic (re-run equality verified post-format), sorted keys, no timestamps.
- Every catalogued source is included in the JSONL; nothing was dropped. The extractor's two inputs are the only upstream sources; upstream drift re-runs produce a new dated inventory (no in-place overwrite).

## 3. Strategy-provider trace matrix (family level, 5 lanes)

| Strategy lane | Trace status | Primary gap |
|---|---|---|
| MASTER-00 cycle/shadow arbitrage | PARTIAL | no governed live quote stream (P0-2-R gate) |
| SX-01..SX-14 typed contracts | UNKNOWN | no StrategyDataRequirement/CompatibilityEvaluator (W14) |
| R10 detectors/CPMM binding | PARTIAL | ONE_SHOT capture only; historical live attempt = transport error + 0 snapshots |
| R02 flash-capital CAP-A/B/C/D | PARTIAL | all 27 candidates disabled; effective capacity UNKNOWN |
| Paper/shadow qualification | MISSING | no EventEnvelope producer (PR #680 trace) |

Static `source_modes` recorded: STREAMING none wired; POLL_ONLY (public RPC/reference rows); ONE_SHOT (`native_cpmm_capture.py`); UNAVAILABLE (all flash-capital candidates + governed live capture). Observed modes require runtime evidence that does not exist yet — static classification only, per the LLM-free contract's static≠runtime rule.

## 4. Capability gap report (summary; details in `CAPABILITY_GAP_REPORT.md`)

1. **P0 — no runtime observation plane**: zero producers (W10), no observed modes, no freshness/latency/gap measurements.
2. **P0 — effective capacity UNKNOWN everywhere**: 27 disabled candidates; do not infer from API max/TVL/vault balance.
3. **P1 — no machine join strategy↔provider**: SX dossiers document data needs in prose only; W14 creates the typed schema.
4. **P1 — access-not-verified on 21/53 market rows**: license/quota/fee pins missing → BLOCKED_MISSING_PIN typed blockers.
5. **P1 — no DataContract/capability registry**: adapter present ≠ capability observed (W13; coordinate with open #672 schema gate).
6. **P2 — chain-identity/finality/reorg semantics unrepresented** (W13/W15).
7. **P2 — catalog drift risk**: market catalog checked 2026-10-06 vs main 2026-11-22; re-verification scheduled via W13 registry, not by editing history.

## 5. What this lane does not claim

No live evidence, no enabled providers, no qualification, no scope changes to canonical owners (`src/market/source_catalog.py`, `FlashCapitalGraph`, `ExternalContractRegistry` untouched). Fixtures are never live evidence; unknown is never zero.
