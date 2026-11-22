# pmm-sim caller-profile qualification — final report (PR #665 implementation slice)

Generated: 2026-11-22. Research-only evidence; PR stays Draft; no merge without human approval.

## Headline results

- **2700/2700 scenarios completed with explicit terminal statuses** (2700 unique scenario
  ids, exactly one terminal record each, 0 conflicts, 0 offline violations):
  **1611** `OK_COMPLETE_ROUND_TRIP`, **933** `FORWARD_SWAP_FAILED` (deterministic, dominantly
  beyond-depth amounts), **156** `REVERSE_SWAP_FAILED`. Deterministic failures are explicit
  classified outcomes — never missing records.
- **No caller-dependent preferential pricing observed for HumidiFi** at slot 401101387:
  `caller_delta_bps` vs DIRECT = **0.0** for every MAGNUS_NATIVE / JUPITER_SIM / OKX_SIM /
  TITAN_SIM row across all 315 fully-OK groups (all row labels `NO_DIFFERENCE`). The only
  differential finding is **reliability**: `DFLOW_SIM` fails forward swaps on 408 scenarios
  vs 105 for the other profiles (dflow spoof router-ix variant incompatible with several
  HumidiFi layouts at this pin). No `BEST_SIMULATED_CALLER_PROFILE` label was earned.
- Synthetic-vs-genuine separation preserved: all spoof profiles + harness-shipped-router
  rows = `SYNTHETIC_SIMULATION` (no mainnet meaning); DIRECT rows on the pinned snapshot =
  `GENUINE_EXECUTABLE_ROUTE_CANDIDATE` (315 `BEST_REAL_EXECUTABLE_ROUTE` labels). Genuine
  official aggregator-route validation remains `BLOCKED_PROVIDER_CALLS_DISABLED`.

## Measured throughput (validation subset, 48 scenarios, batched mode)

| mode | wall-clock | throughput | outcome equality vs isolated |
| --- | --- | --- | --- |
| isolated, workers=1 (per-scenario process) | 5.3 s | 9.0 scen/s | baseline |
| batched, workers=1 | 3.4 s | 14.22 scen/s | 48/48 identical (status, integer amounts, CU, errors) |
| batched, workers=2 | 2.7 s | 17.79 scen/s | 48/48 identical |
| batched, workers=3 | 2.0 s | 24.12 scen/s | 48/48 identical |

Full matrix (2700 scenarios, batched, workers=3): **20.1 s wall-clock, 134.18 scen/s**,
180 batches, 0 retries exhausted (`BLOCKED_INFRA` count 0), `ZERO_CONFIGURED_RPC_ATTEMPTS`.
Worker utilization: 3 parallel batch workers; bounded by SVM process init, not swap compute.

## Batched execution decision (Gate B)

- Code proof: writable metas of both swap directions = {payer, market, base_ta, quote_ta,
  wallet ATAs}; `set_accounts(&pmm_accs)` wholesale-overwrites market/TA snapshot bytes and
  `reset_wallet` re-creates wallet ATAs (`env.rs:71-81,152-156`, `cfg.rs:209-235`,
  `builder.rs:131-149`); program/param/clock/token-program metas are read-only.
- Empirical proof: contamination probe `[1000, 64000-fail, 1000]` — the failed 64000 leaks
  nothing: a 1000 executed AFTER a failed 64000 reproduces the isolated outcome exactly
  (CU 42117, identical amount_out). The apparent "second 1000 fails" case is `AlreadyProcessed`
  — **transaction-signature dedup for repeated identical amounts in one process**, not state
  leakage. Harness constraint recorded: duplicate identical amounts within one batch are
  unsupported (the ladder has none).
- Batched adopted: outputs match isolated exactly under deterministic order ids
  (`PMM_SIM_ORDER_ID` + amount-scoped `gen_order_id_for`).

## Provenance chain

- Upstream: LimeChain/pmm-sim @ `cc4ae891` (MIT, no drift at verification 2026-11-21),
  LimeChain/magnus @ `9ecd34b6` (MIT, `extend-router-ixs` still exactly at pin),
  LiteSVM 0.10 (lockfile), Solana SDK 3.0 line. Mirror `vendor/strategy-research/pmm-sim-cc4ae891/`
  (170 files, SHA256SUMS) + `provenance.json`.
- Tracked patch `upstream_patches/sp665_benchmark_observability.patch` (sha `974955fc…`),
  binary sha `570706cc…`, BUILD_RECEIPT committed. cargo test: 67 passed, 0 failed
  (actual count, reported not assumed).
- Snapshot: upstream static accounts, slot **401101387** (single snapshot; captured slot
  472269598 exists but is `BLOCKED_SIMULATOR_INCOMPATIBLE` — the upgraded HumidiFi ELF
  (sha `433bdfe7…`) does not load in LiteSVM 0.10). `validate_snapshot.py` 15/15 PASS;
  single-slot generation, owners correct, aliases byte-identical.
- Aliases `humidifi-swap-v2.so`/`-v3.so`: lifecycle candidate → **verified** at Gate A
  (all three version-specific instruction layouts executed; 3 + 6 OK rows). Same deployed
  program id `9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp`; recorded as aliases of one
  binary, not independent programs. **Redistribution-license status remains an open dossier
  gap — never inferred from on-chain availability or upstream mirroring.**

## Offline enforcement semantics

- Every invocation: `--jit-accounts=false --jit-programs=false` + the ONLY configured RPC
  endpoint is a local black-hole TCP listener. Result recorded as
  `ZERO_CONFIGURED_RPC_ATTEMPTS` (no connection observed) — **not** a claim of absolute
  process-wide network isolation: OS-level network sandboxing (firewall rule) requires
  elevation unavailable in this environment and is documented as a limitation. Any observed
  connection would be recorded `OFFLINE_VIOLATION` and fail the gate; none occurred.

## Gates

| gate | result |
| --- | --- |
| coverage validator (subset of the 216-cell product) | 8/8 PASS (48 scenarios) |
| Gate A (48 isolated scenarios) | 48/48 unique terminals incl. deterministic expected-failure control `FORWARD_SWAP_FAILED:0x31`; determinism duplicate PASS (CU identical); aliases promoted |
| Gate B (restoration proof + batched-vs-isolated) | code proof + 48/48 equality + contamination probe (restoration proven; dedup constraint documented) |
| Gate C (PAR=1/2/3) | measured throughput table above; outcome equality 48/48 at every PAR |

## Function classification (research vs live)

- **A. Offline historical/market research (this slice):** `capture_snapshot.py`,
  `prepare_runnable_snapshot.py`, `validate_snapshot.py`, `batch_runner.py`,
  `scenario_manifest.py`, `coverage_validator.py`, `merge_results.py` (legacy), verifier.
- **B. Real-time market-data intake:** NOT in this slice — existing governed-capture
  owners only (`src/qualification_campaign/*`, source catalog). No new pipeline.
- **C. Opportunity detection / qualification:** future binding PR through
  `VenueExactLeg`/`RouteQualification` owners (`src/strategy/cpmm_cycle_binding.py`
  lineage) consuming these qualification records — the live path never reprocesses the
  Parquet matrix.
- **D. Live execution / transaction simulation:** R05 exact-simulation + MPR05 owners,
  untouched. No signing, sending, borrowing, or submission anywhere in this slice.

## Flashloan Bot integration

The bot runtime consumes **qualification records** (per-market/per-profile outcomes and
this manifest), not raw benchmark artifacts: the HumidiFi N01 dossier pins the venue; a
future route-binding PR (through existing R13 normalization + R05 simulation + PR130
submission owners) would consult the caller-profile table as evidence — with the recorded
outcome that **no caller profile offers better pricing on HumidiFi at the pinned snapshot**,
so no preferential-caller routing is justified by this evidence. The harness is never
linked into the installed Python runtime.

## Remaining gaps

1. Captured-slot (472269598) execution `BLOCKED_SIMULATOR_INCOMPATIBLE` — needs LiteSVM
   upgrade or newer harness pin; until then the matrix is single-snapshot and **no
   persistent caller-preference claim is made**.
2. Genuine executable aggregator routes: `BLOCKED_PROVIDER_CALLS_DISABLED` (official
   Jupiter V2 /order+/build etc. — separate gated PR).
3. Alias redistribution-license status — open dossier item.
4. `DFLOW_SIM` reliability anomaly — investigate the dflow spoof router-ix variant.
5. HumidiFi production promotion stays BLOCKED (`min_amount_out` ignored — same-tx
   post-balance guard required).
6. OS-level network isolation not enforceable without elevation (black-hole listener
   semantics documented above).
7. Plots not generated (matplotlib not in runtime venv).
