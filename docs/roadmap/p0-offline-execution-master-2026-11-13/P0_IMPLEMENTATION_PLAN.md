# P0 Implementation Plan — dependency graph and bounded PR sequence

**Created:** 2026-11-13
**Baseline:** see [P0_BASELINE.json](P0_BASELINE.json) (main `64a11d33f46291504847cb1bdfd6cdc3dcff5da9`, clean tree).
**Scope law:** market-data P0 only (P0-1 → P0-2 → P0-3). The R-01/R-02/R-03 capital workstream (PRs #583/#586) is a separate lane and is not addressed here.

## 1. Dependency graph

```text
                     ┌────────────────────────────────────────────────────────┐
                     │ PR-0 platform baseline (smallest reviewable unit)      │
                     │  fcntl→Windows fallback (evidence.py),                 │
                     │  os.getuid guard (durability/lifecycle.py),            │
                     │  local LF checkout note for hash pins                  │
                     └───────────────┬────────────────────────────────────────┘
                                     │ (needed only to RUN the gated test
                                     │  suites on native Windows; POSIX/CI ok)
        ┌────────────────────────────┼─────────────────────────────┐
        ▼                            ▼                             ▼
┌───────────────────┐   ┌──────────────────────────┐   ┌────────────────────────┐
│ P0-1 intake       │   │ P0-2 quotes              │   │ P0-3 direct state      │
│ (PR-1)            │   │ (PR-2)                   │   │ (PR-3)                 │
│ extension of      │   │ migration of GPR-02      │   │ beside canonical CPMM  │
│ dynamic_universe  │   │ owner to Jupiter V2      │   │ owner (no 2nd decoder) │
└─────────┬─────────┘   └──────────┬───────────────┘   └───────────┬────────────┘
          │                        │                               │
          ▼                        ▼                               ▼
   P0-1 exit gate           P0-2 exit gate                 P0-3 exit gate
          └────────────────────────┴───────────────────────────────┘
                                   ▼
                        P0 market-data exit gate
                                   ▼
                        P1 (not authorized before)
```

Ordering rules honored from `CODEX_START_HERE.md`:
- P0-1 → P0-2 → P0-3 strictly in sequence (user directive); each is a separate review-only PR.
- PR-0 is a platform enabler, not a feature; it changes no contract and may be merged independently.
- No parallel owners: P0-2 migrates the single GPR-02 quote owner; P0-3 adds venue readers beside the canonical CPMM decoder; P0-1 extends existing discovery/universe/graph owners.

## 2. Platform testing decision (2026-11-13): WSL-first

**Operator decision:** install WSL rather than add an in-repo Windows fallback. Consequences:
- The fcntl-gated suites (`test_gpr02_solana_parallel_radar.py`, `test_din01_bounded_discovery.py`, `test_qpr03_source_intake.py`) and the two `os.getuid()` tests are verified inside WSL, not native Windows.
- A **separate Linux venv is required inside WSL** (the repo `.venv` holds Windows binaries and cannot be reused).

WSL setup and verification commands (to run inside WSL after install):
```bash
sudo apt update && sudo apt install -y python3.13 python3.13-venv git
python3.13 -m venv .venv-wsl
.venv-wsl/bin/python -m pip install "pytest==9.0.3" "pytest-asyncio==1.3.0" "pytest-socket==0.7.0" "hypothesis==6.138.15"
git config core.autocrlf false   # inside WSL checkout only; keeps hash pins LF-native
.venv-wsl/bin/python -m pytest tests/test_gpr02_solana_parallel_radar.py tests/test_din01_bounded_discovery.py tests/test_qpr03_source_intake.py tests/test_native_cpmm_qualification.py -q
```

**PR-0 (in-repo Windows fallback) is deferred, not cancelled:** if WSL proves impractical, revisit the minimal `msvcrt`/`getuid` fallback described below — it remains the designed alternative.

<details><summary>PR-0 original description (deferred)</summary>

**Problem (from baseline):**
1. `src/qualification_campaign/evidence.py:11` imports `fcntl` (Unix-only) → `CampaignEvidenceStore` unusable on Windows; 3 test modules cannot even be collected.
2. `src/durability/lifecycle.py:378` calls `os.getuid()` → 2 governed-collector tests fail on Windows.
3. Local `core.autocrlf=true` rewrites LF→CRLF on disk → byte-hash pins in `config/jupiter_endpoint_quarantine.json` mismatch locally (LF-normalized hashes match; repo content intact; CI unaffected).

**Deliverable:** POSIX behavior byte-identical (`fcntl` path kept), Windows path uses `msvcrt` locking / uid-guarded logic; a short `VERIFY-WINDOWS.md` note documenting the LF re-checkout command for hash-pinned files. No gate weakened, no quarantine weakened.

**Acceptance:** full P0-relevant test subset green on Windows and (via CI) Linux.
</details>

**Local remediation applied 2026-11-13 (no code change, no config change):**
```bash
rm src/solana_parallel_radar/cli.py src/solana_parallel_radar/probes.py
git -c core.autocrlf=false checkout -- src/solana_parallel_radar/cli.py src/solana_parallel_radar/probes.py
```
Result: both pinned files are LF on disk (sha256 `f699fba3…` / `c7262a81…`), quarantine suite 24/24 passed. Note: a plain `git checkout` is a no-op here (files stat-match the index); the delete-then-checkout forces the LF rewrite.

## 3. PR-1 — P0-1: Safe Solana indexed intake → Dynamic Universe

**Reuse (canonical owners, no new data plane):** `SourceIntakePlane`, `SourceDossier`, `deduplicate_candidates`, `DynamicUniverse`, `AssetRegistry`, `AssetIdentity`/`RESOLVE_LIVE`, `SolanaMintVerifier`, `Token2022SemanticsPolicy`, `SolanaResearchAdapter`, `VerificationQueue`, `RecoverableStreamJournal`/`CampaignEvidenceStore`, `ProviderGovernance`.

**Build items (dependency order):**
1. **Discovery lane completion** — DEX Screener pagination/search bounding, Raydium API V3 pool list paging cursors, Meteora DLMM pool list paging, Manifest books; each lane: per-page row-rejection counters, response-hash, byte bounds, 429/Retry-After, negative receipts. (`src/market/discovery.py` + `src/solana_parallel_radar/radar.py`)
2. **Continuous bounded polling cadence** (currently `CONTINUOUS_CAPTURE_NOT_IMPLEMENTED`): configurable interval/admission per source, journal-backed, budget-rotating; never retires a pool from partial/truncated/failed pages (complete-snapshot rule already tested in `universe.py`).
3. **Identity gate on intake**: every pool row → mint identity via `RESOLVE_LIVE` + mint-account proof before `IDENTIFIER_VERIFIED`; Token-2022 extension decode mandatory; ticker-only binding already fails closed — add explicit tests.
4. **Shared-liquidity alias groups**: cross-source dedupe already provenance-preserving; add venue-overlap/correlation group emission for downstream P0-2 route-overlap metadata.
5. **Coverage report + hot-pair target**: configurable research target (120–160) accepted only from measured coverage; source coverage receipt (accepted/rejected/duplicate/stale per source).
6. **Fixture replay + schema-drift/negative fixtures per lane**; zero-socket replay (pytest-socket already in dev deps).
7. **DIN-01/GPR-02 CLI wiring** for the new lanes + campaign receipts (existing schemas `prequal.*`, `dynamic-universe.campaign.v1`).

**Explicitly out:** GeckoTerminal stays BLOCKED (`CURRENT_DOCS_PIN_MISSING`); no executable edges from indexed rows; boot-path wiring deferred (PLANNED, separate decision).

**Exit gate:** offline tests for normalization/dedup/lifecycle/partial-safety/identity/Token-2022; byte-stable replay; coverage receipt; `IN_MAIN_VERIFIED`/`IMPLEMENTED_UNQUALIFIED`/`BLOCKED` classification per source in `P0_1_REPORT.md`.

## 4. PR-2 — P0-2: Jupiter V2 + 0x comparable quotes

**Precondition:** PR-1 open (sequence), PR-0 merged or test subset runnable.

**Known drift (confirmed in main):** `probes.py:292` + `cli.py:164` use V1 `/swap/v1/quote`; V1 files are byte-hash-pinned by `config/jupiter_endpoint_quarantine.json` → **migration must update those review hashes in the same PR** (the guard is designed for exactly this).

**Build items:**
1. V2 request builder: `GET https://api.jup.ag/swap/v2/order` with `inputMint`, `outputMint`, exact base-unit `amount`, `slippageBps` recorded; `taker` omitted for quote-only or same public taker as 0x for taker-aware mode; never `/execute`; never `lite-api.jup.ag`.
2. Distinct V2 normalizer (`normalize_jupiter_v2`) — V1 parser retained for quarantine history; V1 fixtures must be rejected by the V2 parser and vice versa (explicit compatibility tests).
3. WSOL vs native SOL sentinel reconciliation recorded explicitly per request.
4. 0x path: keep existing governed POST owner; add taker-parity enforcement in `compare_quotes` (same public taker on both providers or quote-only mode explicitly distinguished); do not synthesize slots (0x slot stays null).
5. Route-plan/venue-overlap metadata: carry route program/label legs into evidence so aggregator overlap is visible (feeds correlation groups from PR-1).
6. Fixtures: V2 success, no-route, 400/401/403/429/5xx/timeout, malformed amount, mint mismatch, missing fields, stale, schema drift; 0x equivalents incl. instructions/LUT presence but never deserialized into signer-capable flow.
7. Replay: retained captures replay byte-stable, zero network; `execution_authority=false`, `production_promotion=false` preserved.

**Credentials (names only):** `JUPITER_API_KEY`, `ZEROX_API_KEY` (repo canonical; keep). Not configured in this environment → live capture BLOCKED until user opt-in; offline work unaffected.

**Exit gate:** V2 fixtures match pinned OpenAPI; 0x parser matches extract; unit tests for identity/base-units/fees/staleness/null-slot/failure classes; redacted real captures (only if user supplies keys + opt-in); offline replay; `P0_2_REPORT.md`.

## 5. PR-3 — P0-3: exact direct-state verification

**Precondition:** PR-2 open (sequence).

**Build items:**
1. **Audit + keep** `src/providers/raydium_cpmm_native.py` as canonical CPMM owner (already IN_MAIN_VERIFIED, 17+ fault classes).
2. **Fix defect:** wrong DLMM program ID `LBUZKhRxPF3XUpBCjp4YzTKgLLjggiJWUna9LZJRQD3` + bogus Orca variant in `src/config/addresses.py:45` / `src/ingest/amm_math_dispatcher.py` / `src/ingest/tx_builder.py:669` — correct to pinned canonical IDs; quarantined paths may only receive the ID correction, not behavior promotion.
3. **Raydium CLMM reader** (new, beside CPMM): PoolState + TickArrayState + bitmap extension decode per pinned `vendor-reference/raydium/clmm/*`; integer Q64.64 swap math with direction-specific initialized-tick traversal; differential vectors from Apache-2.0 pinned `tick_math.rs.txt`/`swap_math.rs.txt`.
4. **Meteora DLMM reader**: LbPair + BinArray + BinArrayBitmapExtension + Oracle decode per pinned IDL; per-bin price/fee math; dynamic fee; reject missing/stale bins.
5. **Orca**: stays `BLOCKED_LICENSE_REVIEW`; only the existing `mpr2617.py` offline proof validator remains; no decoder.
6. **Slot-coherence policy**: pool + vaults + ticks/bins under bounded slot skew (reuse `minContextSlot` discipline and `RootedRpcQuorumPolicy`); reject stale/missing dependencies.
7. **Evidence vocabulary**: extend the existing `PromotionStage`/`evidence_kind` owners with the dossier's classes (`INDEXED_CANDIDATE`, `IDENTITY_VERIFIED`, `POOL_ACCOUNT_VERIFIED`, `VENUE_STATE_DECODED`, `AMOUNT_SPECIFIC_QUOTE`) — extension of the canonical enum, not a parallel vocabulary.
8. **Negative fixtures** per the task's mandatory list (wrong owner, discriminator, length, mint/vault, token program, Token-2022 mismatch, stale slot, paused, missing tick/bin, zero liquidity, multi-tick/bin crossing, rounding edges).
9. **Fixture provenance**: differential vectors only from license-compliant pinned sources (Raydium Apache-2.0, Meteora ISC IDL) or reproducible fixtures from observed public chain data; document assurance gap where no SDK vector is usable.

**Exit gate:** every claimed venue/version has offline decoder fixture + exact-in differential test; unknown program versions fail closed; no quote from incomplete tick/bin data; live RPC read-only capture separately bounded; `P0_3_REPORT.md` + decoder version matrix.

## 6. PR sequence and gates

| PR | Scope | Depends on | Merges |
|---|---|---|---|
| P0-0 PR | Baseline artifacts (P0_BASELINE.json + this plan) | — | review-only, human approval |
| PR-0 | (DEFERRED — WSL chosen) Windows platform compat (fcntl, getuid) + platform verify doc | — | independently, if revisited |
| PR-1 | P0-1 intake → Dynamic Universe | P0-0 PR opened; WSL for gated-suite runs | review-only, human approval |
| PR-2 | P0-2 Jupiter V2 + 0x comparability (incl. quarantine hash update) | PR-1 opened | review-only, human approval |
| PR-3 | P0-3 CLMM/DLMM readers + ID defect fix + evidence vocabulary | PR-2 opened | review-only, human approval |

**No merge without explicit human approval** (§0 rule 9). Each PR carries: `P0_x_REPORT.md`, machine-readable status receipt, fixture manifest, evidence hashes, source pins, blockers, exact replay commands.

## 7. Standing blockers (from baseline)

| ID | Blocker | Owner | Unblocks |
|---|---|---|---|
| B-ENV-1 | ~~`core.autocrlf=true` locally mismatches LF hash pins~~ | RESOLVED locally 2026-11-13 (forced LF re-checkout; no config change) | local hash-pinned verification works |
| B-ENV-2 | `fcntl` in `src/qualification_campaign/evidence.py` (Unix-only) | operator WSL install (chosen 2026-11-13); PR-0 fallback deferred | WSL runs of GPR-02/DIN-01/QPR-03 suites |
| B-ENV-3 | `os.getuid()` in `src/durability/lifecycle.py:378` | same (WSL) | WSL runs of governed-collector tests |
| B-P02-1 | `JUPITER_API_KEY` not configured | user opt-in | Jupiter live capture |
| B-P02-2 | `ZEROX_API_KEY` + public taker not configured | user opt-in | 0x live capture |
| B-P02-3 | 0x has no machine-readable OpenAPI pin (extract only) | separate bounded re-fetch before live qualification | 0x live qualification |
| B-P03-1 | Orca license review | user/legal | Orca decoder (stays BLOCKED until then) |
| B-P03-2 | no real mainnet account bytes in repo | bounded read-only RPC capture (opt-in) | real-state differential tests |
| B-P01-1 | GeckoTerminal docs pin missing | fresh official snapshot | GeckoTerminal lane |
| B-P01-2 | historical Jupiter/RPC/STON proxy denial — counts must be re-verified | bounded live diagnostic | trusting historical 245/21/24 counts |

## 8. Safety invariants (all PRs)

No private keys, no signing, no sending, no transaction submission, no borrowing, no account creation, no spending, no production promotion, no env-flag gate bypass. All returned instruction/transaction bytes are inert evidence. Comparison and capture stay `execution_authority=false`, `production_promotion=false`. All 37 governed sources remain `enabled: false` until separately qualified.
