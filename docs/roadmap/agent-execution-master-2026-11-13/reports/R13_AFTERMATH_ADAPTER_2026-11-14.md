# R13-A2 — Aftermath (Sui) quote adapter (lane report)

**Lane:** R13-A2 (wave-3). **Implemented:** 2026-11-19/20. **Base:** main `288e1b61`
(worktree branch `agent/r13-aftermath-adapter`). **Model:** mirrors merged
`src/solana_parallel_radar/providers/titan.py` (#647) adapter style against the
frozen kernel #638.

## Deliverables (exact changed paths)

- `src/gpr_sui_shadow/providers/__init__.py` — verbatim move of the 210-line
  GPR-03 owner `providers.py` (package conversion so the new submodule can
  join without shadowing; public import surface preserved, regression-tested).
- `src/gpr_sui_shadow/providers/aftermath.py` — NEW adapter owner.
- `tests/test_r13_aftermath_adapter.py` + `tests/fixtures/r13_aftermath_adapter/trade_route_exact_in.json`.
- `docs/integrations/offline/aftermath-adapter-2026-11-19/AFTERMATH_ADAPTER_SCHEMA_PIN.md` — NEW additive dossier.
- `config/format_targets.txt` — adapter appended (CI black gate).
- Kernel (`src/execution/quote_build_kernel.py`) UNTOUCHED (frozen #638).

## Source pins

Wave-1 `AFTERMATH_SUI.md`, wave-2 `AFTERMATH_ROUTER_WAVE2.md`, additive
`aftermath-adapter-2026-11-19/` (production OpenAPI
`https://aftermath.finance/api/openapi/spec.json`, license MIT, retrieved
2026-11-19 + official docs pages). Two wave-1 typed gaps RESOLVED by the new
pin: `/api/router/transactions/trade` now declared (deprecated; v1
`TransactionKind` replacements documented) and the `n`-suffixed BigInt wire
encoding pinned. Both recorded in the dossier; the adapter still consumes the
QUOTE surface only (build ≠ quote).

## Fail-closed properties shipped

- No transport ships: `normalize_via_transport(None, ...)` → typed DISABLED;
  live verdict always `BLOCKED / AFTERMATH_LIVE_CAPTURE_NOT_AUTHORIZED`
  (no code path can authorize; mirrors `LIVE_SUI_PROVIDERS_NOT_AUTHORIZED`).
- UNKNOWN is never zero: no min-out field pinned → `minimum_output_raw=None`;
  no slot/checkpoint/expiry pinned → freshness carries only
  caller-supplied `received_at_ns`; externalFee has no amount → `None`.
- Strict pinned decoders: `BigIntInput` 3 forms only (int / decimal string /
  `"…n"`); poolId must be a Sui object id; portion bounded by the pinned 1e18
  scale; `share_bps` filled only on exact division (never rounded).
- HTTP-200 error envelopes (`{error}` / `{error_code,message}` / string / null)
  are typed failures BEFORE quote parsing (pinned "data.error is primary signal").
- Nonzero `coinIn/coinOut.tradeFee` refused as drift against the pinned "no
  protocol fee on SOR trades" fee model (typed COMPARABILITY_DRIFT).
- One response = one operator observation: group `aftermath-sor`, lineage
  `("aftermath", *path protocols)` — Aftermath quotes correlate with direct
  Cetus captures via lineage + shared pool object ids (overlap notes).

## Test evidence (offline, pytest-socket)

- `tests/test_r13_aftermath_adapter.py`: 26 unit tests — positives (kernel
  field mapping, correlation, pools, share_bps, fees, tenth-decimal amounts),
  13 typed-negative refusals, disabled stance, race seam, dedup verdicts,
  no-extrapolation, GPR-03 import-surface regression.
- Regression suites re-run unchanged: `tests/test_gpr03_remediation.py`,
  `tests/test_r13_quote_race_contract.py`, `tests/test_r13_kernel_contract.py`,
  `tests/test_r13_titan_adapter.py`.
- Exact pass/fail counts recorded in the PR body at open time.

## Blockers / out of scope

- Funnel/intake wiring (GPR-03 funnel + P0-2 probes) — DEFERRED follow-up lane.
- PTB composition normalization (v1 add-trade `TransactionKind`) — builder
  surface owned by R-03; never built/decoded/signed here.
- Aftermath flash-lender status: MISSING_PIN carried from wave-2 (no Move
  flash API documented) — discovery ≠ capital.
- Provider stays DISABLED; live/sign/send hard-denied.
