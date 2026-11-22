# COMPLETE STRATEGY AND DATA-SOURCE READINESS AUDIT (OCA readiness lane)

- **Date:** 2026-11-22 · **Base main SHA:** `0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54`
- **Branch:** `codex/oca-strategy-readiness-audit-2026-11-22` · **Mode:** AUDIT_ONLY (read-only over canonical owners)
- **Machine-readable matrix:** `READINESS_MATRIX.json` (schema `studious.readiness.audit.v1`) + `verify_readiness_matrix.py` (zero-network verifier — **verification OK**)
- **Governance:** #683 = master dependency DAG; #679 = CAMPAIGN_START/WIN owner; #666 head `bb38a1fe` = design source. No canonical owner duplicated; no second graph/journal/quote engine/deduplicator created.

## 1. Scope

Strategic scope: **Solana CPMM, CLMM, DLMM** using existing market/venue owners. **Project 0 (MarginFi), Jupiter Lend, Kamino** evaluated **separately as capital providers** (financing legs — never market-liquidity evidence).

## 2. Strategy verticals (evidence-linked rows in the matrix)

| Vertical | Owner path | States (ladder) | Source mode | Chain weakest link | Blockers |
|---|---|---|---|---|---|
| Solana CPMM atomic | `src/providers/raydium_cpmm_native.py` (+ `cpmm_math.py`, `exact_cpmm_capacity.py`) | DECLARED✓ DOCUMENTED✓ IMPLEMENTED✓ TESTED✓ **CAPTURED✗ RUNTIME_OBSERVED✗** | **ONE_SHOT** (never report as STREAMING) | provider→raw PARTIAL; durable capture cursor MISSING; paper reconciliation UNKNOWN | BLOCKED_AUTHORIZATION (P0-2-R/P0-3-R) |
| Solana CLMM atomic | `src/providers/raydium_clmm_native.py` | DECLARED✓ DOCUMENTED✓ IMPLEMENTED✓ TESTED✓ CAPTURED✗ RUNTIME_OBSERVED✗ | **UNAVAILABLE** | provider→raw MISSING (no CLMM capture owner) | BLOCKED_AUTHORIZATION + BLOCKED_MISSING_CAPTURE_OWNER |
| Solana DLMM atomic | `src/providers/meteora_dlmm_native.py` | DECLARED✓ DOCUMENTED✓ IMPLEMENTED✓ TESTED✓ CAPTURED✗ RUNTIME_OBSERVED✗ | **UNAVAILABLE** | provider→raw MISSING (no DLMM capture owner) | BLOCKED_AUTHORIZATION + BLOCKED_MISSING_CAPTURE_OWNER |

Tests verified to exist on the pinned SHA (CPMM: fee accounting, split replay, exact capacity, native qualification fixtures; CLMM/DLMM: native quote completion, mixed route binding, fixtures).

## 3. Capital providers (separate legs)

| Capital | Owner | States | Capacity evidence | Blockers |
|---|---|---|---|---|
| Project 0 (MarginFi) | `src/providers/marginfi/` | DECLARED✓ DOCUMENTED✓ IMPLEMENTED✓ TESTED✓ CAPTURED✗ RUNTIME_OBSERVED✗ | **effective flash capacity UNKNOWN** (R-02 gate; never inferred from API max/TVL/vault) | BLOCKED_LIVE_EVIDENCE_GATE |
| Jupiter Lend | `src/lending/jupiter_lend.py` | same ladder through TESTED | PARTIAL_DECODED; capacity UNKNOWN | BLOCKED_LIVE_EVIDENCE_GATE |
| Kamino | `src/lending/kamino.py` + `kamino_real_conformance.py` + unsigned builders | same ladder through TESTED | PARTIAL_DECODED; **flash ABI/IDL unpinned** | BLOCKED_MISSING_PIN |

## 4. Provider inventory refs

`src/resources/market_source_catalog.json` — 53 rows, **0 enabled**; `PROVIDER_CATALOG.json` — 27 flash-capital candidates, **0 enabled** (`RND_ONLY_27_OPTIONS_ALL_DISABLED_NO_LIVE_CAPITAL`). Source modes across the inventory: STREAMING **none wired**; POLL_ONLY public RPC/reference rows; ONE_SHOT `native_cpmm_capture.py`; UNAVAILABLE all flash-capital candidates. Offline dossier bundles: `docs/integrations/offline/solana-p0/`, `providers-wave1-2026-11-13/`.

## 5. Existing adapters and exact missing joins

Per-row `chain` objects record provider→raw evidence→cursor/gaps→MarketObservation→strategy→decision→paper-outcome statuses (PARTIAL/MISSING/UNKNOWN — unknown never zero). Exact missing joins: governed live quote/state streams (authorization), durable capture cursor/gap journals per venue, CLMM/DLMM capture owners, observation promotion evidence, reconciliation evidence for paper outcomes, Kamino ABI/IDL pin, quorum-gated rooted capital reads.

## 6. Verifier

`verify_readiness_matrix.py` validates schema, state vocabulary, path/test existence on the pinned checkout, mode vocabulary and absence of live-capability claims — **OK** (exit 0). Deterministic; zero network.

## 7. What this audit does NOT claim

No live/RPC/capture evidence of any kind; `RUNTIME_OBSERVED` is false everywhere pending OCA-W10-verified producers per route; the graph/catalogue/SDK presence and HTTP 200s never imply live data capability; unknown ≠ zero.
