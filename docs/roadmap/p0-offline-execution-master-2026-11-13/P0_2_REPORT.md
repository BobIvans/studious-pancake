# P0-2 Report — Jupiter Swap API V2 + 0x comparable quote capture

**Status:** `IMPLEMENTED_UNQUALIFIED` — merged into main via PR #604 (commit `8c3f4dcd`); this document completes the task-required report deliverable and records the reconciliation with this session's parallel work.
**Merged owner (canonical):** `src/solana_parallel_radar/probes.py`, `funnel.py`, `qualification.py`, `cli.py` at main `31a5985b`.
**Date:** 2026-11-14

## Reconciliation note (duplicate-work disclosure)

This session produced a complete P0-2 implementation on branch `codex/p0-2-jupiter-v2-0x-quotes-2026-11-13` (opened as PR #596). While it was in review, an external parallel-agent coordinator ("master-parallel-coordinator", worktrees under `../sp-worktrees/`) snapshotted the in-flight working tree and its lane B landed an equivalent migration as PR #604. Per the master rule — reuse canonical owners, never create a third owner — PR #596 was closed as superseded; the merged main code is canonical and this report documents it.

## What main now implements (verified against `31a5985b`)

- **Jupiter Swap API V2** `GET https://api.jup.ag/swap/v2/order`: required `inputMint`/`outputMint`/base-unit `amount`, `ExactIn`, explicit `slippageBps`, optional public `taker`; V1-only parameters dropped; native-SOL sentinel rejected in both pinned quote contracts (WSOL registry mint is the only SOL representation).
- **Distinct V2 parser** (`normalize_jupiter_v2`): V1 payloads (`contextSlot`) rejected, never reinterpreted; V2 markers required (`mode`, `router`); request/response identity (mints, amount, slippage echo, taker echo); bounded route plan; `slot` stays `null` — the V2 order response has no context slot and none is synthesized; a present `transaction`/`errorCode` disqualifies comparison (bytes remain inert evidence).
- **0x**: governed `POST /solana/swap-instructions` retained; `ZEROX_API_KEY` single canonical name; public taker only.
- **Comparable race invariants**: same pair, same exact base-unit amount, same taker mode, explicit slippage, bounded freshness; losing quotes retained; no cross-size extrapolation; `execution_authority=false`, `production_promotion=false`.
- **Evidence**: redacted raw responses, hashes, provider generations, route/fee metadata (router/mode/requestId/fees/per-leg amm-label-amounts for Jupiter; dex/amount/ppb for 0x), slots only when a source actually provides one.
- **Quarantine re-review**: `config/jupiter_endpoint_quarantine.json` research-reference pins repointed to V2 with hashes of the merged files; production `/swap/v2/build` contract and all forbidden markers unchanged; `MPR-NEXT-08` verifier tests pass on the merged checkout.
- **Pins**: `jup-ag/docs@d40d9369` (blob `c8bad7a7…`) via the checked-in offline bundle (`verify_offline_bundle.py` exit 0); `live_provider_schema_verified=false` unchanged.

## Verification of the merged state

- `MPR-NEXT-08 Jupiter V2 contract and quarantine`: pass on main (24/24).
- `deterministic-read-only` (GPR-02 radar suite, Linux): pass on the #604 merge.
- Local Windows native run against the R-11 shim state: `tests/test_gpr02_solana_parallel_radar.py` + DIN-01 + QPR-03 intake + P0-1 cadence suites — 131 passed, 1 skipped (fcntl gate resolved by the merged R-11 shim; WSL no longer required for these suites).
- Offline bundle verifier: exit 0 (re-checked).

## Remaining P0-2 blockers (unchanged)

| ID | Blocker | Owner |
|---|---|---|
| B-P02-1 | `JUPITER_API_KEY` not configured | user opt-in for bounded live capture |
| B-P02-2 | `ZEROX_API_KEY` + public taker not configured | user opt-in for bounded live capture |
| B-P02-3 | 0x has no machine-readable OpenAPI pin (extract only) | bounded re-fetch before live qualification |

## Safety

No `/execute`, no signing, no transaction submission, no borrowing, no account creation, no spending, no production promotion. Returned instruction/transaction bytes are inert evidence. No live API requests were made during this work; live capture remains the separately opted-in governed command.
