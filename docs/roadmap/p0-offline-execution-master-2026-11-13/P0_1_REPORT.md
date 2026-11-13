# P0-1 Report — Safe Solana indexed intake → Dynamic Universe

**Status:** `IMPLEMENTED_UNQUALIFIED` (offline implementation + fixtures + deterministic replay delivered; real bounded live capture remains a separately opted-in command and was **not** executed)
**Branch:** `codex/p0-1-solana-intake-dynamic-universe-2026-11-13` (review-only PR)
**Base main SHA:** `64a11d33f46291504847cb1bdfd6cdc3dcff5da9`
**Date:** 2026-11-13

## What was delivered

One new module plus canonical-owner wiring, per the P0-1 task and the baseline plan:

1. **`src/solana_parallel_radar/intake_cadence.py`** (new)
   - `CadencePolicy` — configuration-pinned per-source pacing bounds (interval, page walk ≤8, backoff multiplier, backoff ceiling, Retry-After ceiling).
   - `IntakeScheduler` — deterministic bounded multi-round paging/rounds **through the canonical `SourceIntakePlane`**: quota admission, dossier/profile generation checks, evidence journaling and secret redaction stay owned by the plane. Conservative stop rules: healthy empty page ends a walk (next round may resume); 429/HTTP/transport errors apply bounded backoff honoring a bounded `Retry-After`; a denied attempt cap (`quota-or-admission-denied`) is permanent for the campaign; a physical-request budget bounds the whole run. Indexed pages are never treated as a complete snapshot — retirement stays a `DynamicUniverse` decision.
   - `radar_universe_envelopes` — fail-closed bridge from retained radar observations into the existing `DynamicUniverse` owners: only chain-proven mints become `CandidateAsset`s; only fully proven pairs become research-only `MarketIdentity` rows with `fee_tier="unverified"`, `program_id="indexed:<family>"` (explicitly an indexed family label, never a program-owner proof) and `correlation_group="solana:<pool>"`. Unproven identities are counted rejections (`identity_unverified_mints`, `identity_proof_mismatch`), never silently dropped and never promoted. Indexed venue labels are mapped to canonical venue families via a reviewed table; unmapped labels (e.g. `orca`) are explicit `unknown-venue-family` rejections, which is what makes cross-source aliasing dedupe to one research record.
   - `coverage_report` — machine-readable `p01.source-coverage.v1` receipt: per-source physical calls, quality states, correlation group, docs-pin timestamp, `PARTIAL_INDEXED_PAGES_ONLY` completeness, duplicate rows merged, identity verification counts, blocked sources, and the configurable hot-pair research target. The target is **never forced**: it only reports `TARGET_NOT_SUPPORTED_BY_MEASURED_COVERAGE` vs `TARGET_WITHIN_MEASURED_COVERAGE`. Exact/paper/production are hard-coded `BLOCKED`.
2. **`src/solana_parallel_radar/din_discovery.py`** (extended, +134/−9)
   - `parse_cadence` — operator cadence config validated fail-closed (unknown keys rejected).
   - `reviewed_sources(..., request_limit, campaign_attempt_cap)` — quota params threaded without changing default one-shot behavior.
   - `capture(..., cadence=None)` — default behavior byte-identical (existing tests unchanged); with cadence, the scheduler drives rounds and the result gains `round_receipts` and `coverage`. The manifest pins the cadence configuration.

## Deliverable matrix (per task file)

| Requirement | Where | Status |
|---|---|---|
| Per-observation provenance (generation, timestamps, request params, response hash, status, row rejections, capture ID) | existing `SourceIntakePlane` envelope + scheduler `observation_receipts` | IN_MAIN_VERIFIED |
| Bounded polling cadence, quota admission, timeouts, 429, byte bounds, negative evidence | `IntakeScheduler` + existing governance/transport | IMPLEMENTED_UNQUALIFIED (offline-tested; live run opt-in) |
| Complete vs partial snapshots; never retire from partial | scheduler emits `complete=False` envelopes; `DynamicUniverse` retirement untouched (tested in `test_dynamic_universe.py`) | IN_MAIN_VERIFIED |
| Exact identity normalization + alias/correlation groups + dedupe without provenance loss | `Candidate.identity` dedupe (existing) + `VENUE_FAMILY` canonicalization + `correlation_group` emission | IMPLEMENTED_UNQUALIFIED |
| Mint verification (owner/decimals/Token-2022) before handoff | bridge requires `ChainAssetProof` per mint; Token-2022 extensions carried on `CandidateAsset.extensions` | IMPLEMENTED_UNQUALIFIED (live RPC proof remains the documented DIN-01 blocker) |
| Handoff only to existing Dynamic Universe / ResearchEconomicGraph owners | bridge → `DynamicUniverse.ingest`; graph handoff via existing `SolanaResearchAdapter` (unchanged) | IMPLEMENTED_UNQUALIFIED |
| Fixture replay + schema-drift/negative fixtures; zero-socket replay | `tests/fixtures/p01_intake/` (12 fixtures, hash-pinned) + `tests/test_p01_intake_cadence.py`; replay via existing `runner.replay` (`network_reads: 0`) | IMPLEMENTED_UNQUALIFIED |
| Configurable hot-pair target (120–160), never forced | `coverage_report(hot_pair_target=...)` — report-only semantics with explicit status | IN_MAIN_VERIFIED (semantics) / not executed live |
| Campaign receipts + source coverage report | `din_discovery.capture` result: `round_receipts`, `coverage` | IMPLEMENTED_UNQUALIFIED |
| GeckoTerminal stays BLOCKED | `reviewed_sources` docs-pin gate (unchanged): `CURRENT_DOCS_PIN_MISSING` | BLOCKED (by design) |

## Source classification (per P0-1 task)

| Source | Status | Notes |
|---|---|---|
| DEX Screener | `IMPLEMENTED_UNQUALIFIED` | adapter + fixtures; DIN-01 historical capture was HTTP 200 with an empty result |
| Raydium API V3 | `IMPLEMENTED_UNQUALIFIED` | adapter + pagination walk + fixtures; historical 11-candidate diagnostic sample |
| Meteora DLMM Data API | `IMPLEMENTED_UNQUALIFIED` | adapter + fixtures |
| Manifest | `IMPLEMENTED_UNQUALIFIED` | adapter + fixtures; no committed live capture |
| Sanctum | `IMPLEMENTED_UNQUALIFIED` | existing registry ingestor (unchanged this PR) |
| GeckoTerminal | `BLOCKED` | current docs/schema pin missing; no adapter invented |
| Sui lanes | `IMPLEMENTED_UNQUALIFIED` | existing DeepBook ingestor; P1-1 continues Sui scope |

## Evidence hashes (committed tree)

| File | SHA-256 |
|---|---|
| `src/solana_parallel_radar/intake_cadence.py` | `0e2212b6c2645ecd57421d38122e3323de44619c23194985419ca2893f7dfb33` |
| `src/solana_parallel_radar/din_discovery.py` | `cdf04442f15ac5efeac0bab2a7fab56d6252cf50d83ba974c8ab78c24b8ef64e` |
| `tests/test_p01_intake_cadence.py` | `51b272a431b3531589c90549b8720dd5d96dbd60edf2a4a66f8024e10088c2ef` |
| `tests/fixtures/p01_intake/fixture-manifest.json` | `623db1e213426c6b1a0f38dc54e390569fd70b8c7822cf170ac98a8b09d9d4ed` |

(`din_discovery.py` hash is pre-commit working-tree content; the PR diff is +134/−9 lines.)

## Tests

`tests/test_p01_intake_cadence.py` (black/flake8 clean):
1. fixture SHA-256 pins fail closed on mutation;
2. per-lane adapter normalization: positive / schema-drift / foreign-chain / rate-limit / program-filter rows;
3. scheduler pagination + healthy-empty-page stop + next-round resume;
4. 429 + bounded Retry-After backoff, resume only when due;
5. attempt-cap denial is permanent for the campaign;
6. physical-request budget breaks at the round boundary;
7. universe bridge: alias dedupe (same pool, two sources → one record), unproven mints → no market row, proof/identifier mismatch rejection, all records stay `DISCOVERED`, nothing `RETIRED`;
8. coverage report: target never forced, unreviewed source rejected, target validation;
9. end-to-end `din_discovery.capture` with cadence over a mock transport → 4 physical calls, 6 receipts, 3 deduped identities, coverage receipt, safety flags false, then `replay` → `replay_identical: true`, `network_reads: 0`.

**Execution status (honest):**
- **Executed locally (Windows):** the dev-equivalent pure-logic paths were executed once via a temporary harness (documented here, not committed): scheduler, bridge, coverage, `parse_cadence`, and all fixture-driven adapter normalizations — **all passed**. The committed pytest module is `fcntl`-gated.
- **Not yet executed as committed pytest:** the whole committed module imports `src.qualification_campaign.evidence` (Unix-only `fcntl`), so per the operator's **WSL-first decision** it runs under WSL or CI Linux. WSL was **not yet installed** at PR-open time; this is blocker B-ENV-2 in `P0_BASELINE.json`. CI (Linux) will run it on push.
- Runnable Windows subset (no regressions from this change): **60 passed** (dynamic universe, asset resolution, Jupiter quarantine contract, promotion campaign). Pre-existing Windows failures (`os.getuid`) unchanged.
- Offline bundle verifier: `python -I docs/integrations/offline/solana-p0/verify_offline_bundle.py` → exit 0 (re-checked on this branch).

## Replay command (zero network)

```bash
# after a real capture:
python -m src.solana_parallel_radar.din_discovery --replay <capture-dir> --output <new-dir>
# committed evidence fixture (historical DIN-01 capture):
# see docs/roadmap/din01-bounded-solana-2026-10-07/REPORT.md
```

The cadence run consumes only retained journal events; `network_reads` is asserted `0`.

## Safety

- No signer, sender, transaction submission, borrowing, account creation or spending code added; no quarantine path weakened; all 37 governed sources remain `enabled: false`; `exact_status`/`paper_status`/`production_status` hard-coded `BLOCKED`; comparison stays `DISCOVERY_ONLY`.
- No live API/RPC request was made during this work. Live bounded capture remains the separately opted-in DIN-01 command with reviewed docs pins.

## Blockers

| ID | Blocker | Owner |
|---|---|---|
| B-ENV-2 | `fcntl` (Unix-only) gates the committed test module on native Windows; WSL not yet installed | operator WSL install (decided 2026-11-13) |
| B-P01-1 | GeckoTerminal docs/schema pin missing | separate snapshot acquisition |
| B-P01-2 | Historical diagnostic counts (245/21/24) stale + proxy-denied; re-verify under bounded live capture | opt-in live run |
| B-P01-3 | Live mint proof (owner/decimals/Token-2022) requires governed RPC quorum | `INDEPENDENT_ROOTED_RPC_PROFILES_REQUIRED` (existing) |

## Next

P0-2 (Jupiter Swap API V2 + 0x comparable quotes) on its own branch after this PR is reviewed — per the strict P0-1 → P0-2 → P0-3 sequence.
