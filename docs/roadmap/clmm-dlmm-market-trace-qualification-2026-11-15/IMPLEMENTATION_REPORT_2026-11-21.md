# Implementation report — CLMM/DLMM exact-state and market-trace integration (PR #660)

**Branch:** `codex/clmm-dlmm-market-trace-qualification-2026-11-15`
**Rebased on:** main `3030fc72` (post-#659, #661, #662, #663). #659 (R10-1) is merged; its
owner `src/strategy/cpmm_cycle_binding.py` was extended in place, never duplicated.
**Evidence class:** fixture/replay only. No live API call, credential probe, RPC read,
signer, private key, account/ATA creation, signing, sending, borrowing, spending,
provider activation or production promotion was performed or enabled.

## 1. Vendor source closure (immutable, blob-verified)

Fourteen new inert reference snapshots were mirrored at the two existing pinned commits
and registered in `docs/integrations/offline/solana-p0/VENDOR_SOURCE_MANIFEST.json` and
`SOURCE_MANIFEST.json` (upstream path, commit, git blob SHA-1, local path, license):

- Raydium CLMM `6d7a0f82d2f293c553c69aaf943377367c6c4cc6` (Apache-2.0):
  `states/tickarray_bitmap_extension.rs`, `states/pool_fee.rs`,
  `states/dynamic_fee_config.rs`, `instructions/swap.rs`, `instructions/swap_v2.rs`.
- Meteora SDK `1532e540db41ac405dbf4c5bb2ddfceaa1f98ff1` (@meteora-ag/dlmm 1.9.15, ISC):
  `helpers/bin.ts`, `helpers/fee.ts`, `helpers/math.ts`, `helpers/u64xu64_math.ts`,
  `helpers/weight.ts`, `helpers/token_2022.ts`, `constants/index.ts`,
  `helpers/derive.ts`, `helpers/index.ts`.

`verify_offline_bundle.py` passes: `OFFLINE_DOC_BUNDLE_OK vendor_files=33` (33 verified
vendor files, zero network).

## 2. Raydium CLMM completion (`src/providers/raydium_clmm_native.py`, extended in place)

- `TickArrayBitmapExtension` decode (1840 B layout, discriminator, pool binding, PDA)
  with the pinned positive/negative 512-bit slot bitmap math; bitmap offsets, boundary
  asymmetry and the next-initialized-array search are verbatim ports, differential-tested
  against the Rust unit vectors (`get_bitmap_offset_test`, `flip_tick_array_bit_test`,
  positive/negative `next_initialized_tick_array_*`, all-bits full-range walk for
  tick spacing 1/10/60). U512/U1024 left-shift truncation is reproduced.
- `PoolState::next_tick_array_index_with_extension_info` loop ported: in-pool search →
  extension fallback → pinned exhaustion (`tick_spacing >= 15` short-circuit included).
  A walk that needs a further tick array with input remaining is a typed rejection
  (`LiquidityInsufficient` / missing-extension semantics) — the previous decoder revision
  drifted silently to the price extreme; that path is gone.
- 80-byte `DynamicFeeInfo` decode + `DynamicFeeConfig` (92 B) decode with padding
  tombstones and full `validate_params` typed rejections. Dynamic-fee state machine
  ported verbatim: `tick_spacing_index_from_tick` (floor semantics), `update_reference`
  filter/decay/reset windows, `update_volatility_accumulator` clamp, quadratic
  `compute_dynamic_fee_rate` with ceiling division and `MAX_FEE_RATE_NUMERATOR` cap,
  `is_fee_on_input` for fee_on 0/1/2 (CollectFeeOn), spacing-bounded step targets and
  the pinned `update_dynamic_fee_index` skipped/nonskipped branches.
- Documented deviation: loop-level tick bookkeeping keeps the existing decoder
  revision (tick == crossed boundary tick) instead of the pinned
  `state.tick = tick_next - 1` convention. Dynamic-fee functions are verbatim ports
  validated against Rust vectors; the per-step index update uses this decoder's tick
  values. Live differential vectors remain a bounded-capture prerequisite.
- Latent bug fixed: `tick_array_start_index` double-decremented the floor for negative
  non-array-aligned ticks (Rust truncates toward zero then decrements once = Python floor
  division). Affects only negative ticks; positive-tick scenes and PDA derivations are
  unchanged, and the existing differential tests pass unchanged.

## 3. Meteora DLMM completion (`src/providers/meteora_dlmm_native.py`, extended in place)

- LbPair decode extended with the IDL-derived static/variable fee parameters
  (filter/decay/reduction periods, min/max bin id, protocol share, function type,
  collect-fee mode, volatility reference/index reference, variable-params timestamp).
  All offsets cross-checked against a full pinned-IDL bytewidth derivation.
- `BinArrayBitmapExtension` decode (1600 B, discriminator from the IDL, pair binding,
  PDA seed `bitmap`) with the pinned `findSetBit` / internal-bitmap search and the
  verbatim `findNextBinArrayIndexWithLiquidity` walk (default window ±512 arrays,
  extension range ±6656, U1024 shift truncation, msb leading-zero semantics).
- Amount-specific exact-in quote `dlmm_swap_exact_in_quote`: verbatim port of the SDK
  `swapQuote` loop (`constants`/`fee`/`bin`/`math` helpers), including base fee law
  (`base_factor * bin_step * 10 * 10^base_fee_power_factor`), variable fee
  (`control * (volAcc*binStep)^2` ceiling), `MAX_FEE_RATE` cap, `FEE_PRECISION = 1e9`
  fee rounding, `splitFee` protocol share with `LIMIT_ORDER_FEE_SHARE`, per-bin fill via
  `getAmountIn/getAmountOut` (mulShr/shlDiv rounding), `updateReference` /
  `updateVolatilityAccumulator` decay, consumed-input semantics with Token-2022
  transfer-fee included/excluded amounts (epoch selection, ceiling inverse), min-out
  slippage, exact rational end price `(10000+binStep)^binId / 10000^binId`, and typed
  rejections for exhausted reachable bins, limit-order pairs (explicit fail-closed
  exclusion), transfer hooks, unknown Token-2022 extensions, epoch-ahead clocks, amount
  overflow and traversal bounds. Partial-fill quotes exist only under an explicit
  `is_partial_fill` flag and are never promotable.
- The legacy `dlmm_amount_specific_quote` sink stays fail-closed (untyped calls rejected).

## 4. Route binding (owners reused, none duplicated)

- `cpmm_cycle_binding.classify_route_support` now takes `exact_venues` (default empty =
  unchanged fail-closed behavior); `evaluate_exact_two_leg_route` gained an
  `adapters: Mapping[VenueKind, ...]` registry resolved per leg's declared
  `venue_kind` (CPMM default adapter unchanged). `QualifiedCpmmState.venue_kind`
  added; `mixed_route_semantic_route_id` added. All 25 existing #659 tests pass.
- New `src/strategy/clmm_dlmm_binding.py`: `QualifiedClmmState`/`QualifiedDlmmState`
  (immutable decoded evidence + account-set hashes + slot/generation/expiry),
  `QualifiedClmmAdapter`/`QualifiedDlmmAdapter` (fail-closed; `NativeCaptureError`
  mapped to typed rejections; partial fills never promotable), `evaluate_exact_mixed_route`
  (2..4 legs, leg k+1 input = leg k conservative output, closes to settlement, no quote
  scaling), R13-K independence via the #659 `_lineage_quote` projection +
  `PoolIdentityDeduplicator.correlation_verdict`, and
  `run_clmm_dlmm_mixed_route_replay` (identity → lineage dedup → generation/slot
  coherence → mixed topology enumeration → exact evaluation → PR118 per-size grid →
  typed fail-closed paper gate) with a deterministic replay digest.
- Replay script: `scripts/clmm_dlmm_market_trace_replay.py` (deterministic; writes
  `replay_report_2026-11-21.json`). Current run: 14 topology routes → 8 unique semantic
  routes → 1 exact quote / qualified / net-positive → paper rejected
  `NO_QUALIFIED_LENDER_EDGE`. Digest
  `09c9fa84b68ca75b03f16005e0baeb7892885a4169e809c66c8083ddff084005`.
  Stage denominators are separate; fixture/replay and live counts are never mixed.

## 5. Jupiter Lend R02/R03 connection (evidence seam only)

The mixed replay's paper stage consumes `evaluate_paper_gate` exactly as #659. The R02
CAP-A reader (`observe_token_reserve_capacity`, `admit_reserve_financing_snapshot`,
`reserve_capital_edge_gate`) and R03 unsigned builders remain the only financing
authority; the binding tests assert the real fixture observation's typed blockers, the
financing port's fail-closed `JUPITER_LEND_SNAPSHOT_REQUIRED`, and that even a
fully-conformant declared seam still refuses paper completion offline
(`SIMULATION_SOURCE_BLOCKED`). Capacity stays UNKNOWN until rooted state proves it;
`flashloan_fee` is never hardcoded from docs (a non-zero fee blocks admission in the
existing owner).

## 6. Tests

- `tests/test_raydium_clmm_meteora_dlmm_native.py` (29) and
  `tests/test_clmm_dlmm_quote_completion.py` (26): extension decode/binding matrices,
  Rust differential vectors, dynamic-fee vectors and quote semantics, DLMM fee/rounding
  vectors, per-bin vector, transfer-fee/hook evidence, bitmap-extension crossing.
- `tests/test_clmm_dlmm_mixed_route_binding.py` (13): cross-venue two-leg exactness,
  support matrix, owner-entry adapter registry, unregistered/repeat-venue rejections,
  generation/slot/staleness coherence, deterministic replay digest, R13-K alias and
  unknown-lineage blocking, blocked candidates, 3-leg mixed cycle, partial-fill and
  walk-exhaustion typed rejections, R02/R03 fail-closed seam.
- Fixtures extended: `tests/raydium_clmm_fixtures.py` (bitmap extension, dynamic-fee
  config/pool), `tests/meteora_dlmm_fixtures.py` (extended pair builder, bitmap
  extension, Token-2022 mint TLV).

## 7. Out of scope / unchanged

No new strategy family, graph, solver, quote kernel, source catalog, transport, RPC
quorum, data store, journal, capital graph, scheduler, signer or sender. No API
activation. Discovery/aggregator sources stay DOCUMENTED / BOUNDED_DISCOVERY_IN_REPO
with LIVE_READ_NOT_AUTHORIZED.

## 8. Actual test evidence (commands and results)

- `python -m pytest tests/test_raydium_clmm_meteora_dlmm_native.py` → 29 passed.
- `python -m pytest tests/test_clmm_dlmm_quote_completion.py` → 26 passed.
- `python -m pytest tests/test_clmm_dlmm_mixed_route_binding.py` → 13 passed.
- `python -m pytest tests/test_sxr1_cpmm_cycle_binding.py` → 25 passed.
- `python docs/integrations/offline/solana-p0/verify_offline_bundle.py` →
  `OFFLINE_DOC_BUNDLE_OK vendor_files=33`.
- `python scripts/clmm_dlmm_market_trace_replay.py` → report written, digest above.
- Full `python -m pytest -q` on this branch: **6171 passed, 10 skipped, 42 failed**
  (plus 1 deselected). Every failure is pre-existing/environmental and none touches
  this PR's files: 41 of the 42 reproduce identically when the same failing test IDs
  are run against unmodified main `3030fc72` (lock/manifest digest drift, CRLF-checkout
  byte-length drift and runtime/security fixture drift in the local snapshot), and the
  42nd (`tests/test_ton_radar_wave2.py::test_wave2_bundle_files_and_hashes_are_intact`)
  fails only because the TON OpenAPI snapshot was checked out with CRLF line endings
  (index stores LF, `git status` shows the file unmodified). The affected failing test
  files: tests/durability/test_pr003_storage_security.py, test_pr041_durable_lifecycle.py,
  tests/runtime/test_mpr_rp03_instance_resources.py, tests/security/test_mpr_td_04_security.py,
  test_decision_calibration.py, test_decision_model.py, test_mpr_close_23_hermetic_runtime.py,
  test_o1_management_evidence_pipeline.py, test_pr025_container_runtime.py,
  test_pr025_packaging.py, test_pr06_management_audit_anchor.py,
  test_pr120_secret_resolver_config_jito.py, test_pr132_observability_integrity.py,
  test_pr170_management_plane.py, test_pr178_artifact_registry.py,
  test_pr183_credential_trust_lifecycle.py, test_pr184_tamper_evident_audit.py,
  test_pr190_canonical_config.py, test_pr196_durable_runtime_kernel.py,
  test_pr205_asymmetric_qualification.py, test_r02_cap_c_offline_replay.py,
  test_super06_research_frontier_closure.py, test_ton_radar_wave2.py,
  tests/deployment/test_pr008_supply_chain.py.

## 9. Remaining human gates (unchanged, independent)

1. Bounded read-only capture campaign authorization (runbook prepared, not executed).
2. Two independent rooted RPC sources with approved profiles/quotas.
3. Live differential vectors for the CLMM dynamic-fee loop bookkeeping deviation (§2).
4. R02 rooted capacity evidence + R03 builder qualification; R05 simulation; R06 QPR.
5. 0x API version/header revalidation before any first request.
