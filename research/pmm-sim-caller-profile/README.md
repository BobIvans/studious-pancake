# pmm-sim caller-profile benchmark results (PR #665 implementation slice)

Deliverable directory for the pmm-sim caller-profile differential benchmark
(pack: `docs/strategy-expansion/2026-11-21/prop-amm-competitive-toolchain/PMM_SIM_CALLER_PROFILE_RESEARCH_RU.md`).

**Research only.** Every spoof-profile row is a LOCAL LiteSVM simulation with a harness-shipped
router-spoof binary and has **no mainnet meaning**. No best aggregator is claimed from this
evidence alone; best simulated caller and best genuine executable route are reported separately;
all activation flags remain false; no signing/sending/borrowing/live.

## Layout

- `market_matrix_v1.json` — the matrix definition (6 caller profiles × HumidiFi v1/v2/v3 ×
  2 directions × 15-amount ladder × snapshots; other pack venues listed NOT_RUN).
- `snapshot/<slot>/` — immutable snapshot provenance records (account bytes digests, slot,
  endpoint class, capture timestamps). CAPTURE_ONLY evidence.
- `results/` — merged per-row records: `caller_profile_results.csv` +
  `caller_profile_results.json` receipt (row counts, classification counts, SHA-256 of the CSV).
- `SUMMARY.md` — findings, caller_delta_bps tables, Protocol-D confound-isolation notes,
  and honest blockers.

## Classification semantics

| classification | meaning |
| --- | --- |
| `SYNTHETIC_SIMULATION` | Spoof profile (JUPITER_SIM/DFLOW_SIM/OKX_SIM/TITAN_SIM) or any row whose router binary is harness-shipped rather than captured deployed bytes. Local research only. |
| `SYNTHETIC_SIMULATION_BY_DEFAULT` | MAGNUS_NATIVE rows using upstream-shipped `magnus-router.so`; promoted only if a captured deployed router binary is byte-equal. |
| `GENUINE_EXECUTABLE_ROUTE_CANDIDATE` | DIRECT rows where the snapshot program bytes are captured deployed bytes (or byte-equal to them). |

Row labels: `BEST_SIMULATED_CALLER_PROFILE`, `BEST_REAL_EXECUTABLE_ROUTE`, `NO_DIFFERENCE`,
`BLOCKED`. Unknown simulator outcomes are counted as neither positive nor negative.

## Known limitations (honest blockers)

- Upstream benchmark uses permissive `expect_amount_out=1`/`min_return=1` — not a production
  slippage or flashloan repayment guard. HumidiFi ignores `min_amount_out`: direct-route
  production promotion stays BLOCKED without a same-transaction post-balance guard.
- Genuine aggregator-route comparison (official Jupiter V2 `/order`/`/build`) is
  BLOCKED_PROVIDER_CALLS_DISABLED in this slice.
- Plots are not generated in this slice (matplotlib is not in the runtime venv); recorded blocker.
- CI verifies committed evidence (digests + classification replay) but cannot rebuild the Rust
  harness; builds are isolated and receipted locally.
