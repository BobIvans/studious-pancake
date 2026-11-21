# Flashloan data-path dossier (OCA-W0C)

- **Date:** 2026-11-22 · **Base main SHA:** `0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54`
- Static, offline, sender-free evidence trace of the full flashloan data path. Nothing here is live evidence; every stage carries its current status.

## Path trace: idea → outcome

| # | Stage | Canonical owner(s) | Status | Evidence |
|---|---|---|---|---|
| 1 | Flash-capital capability graph | `src/economics/flash_capital_graph/graph.py` (`FlashCapitalGraph`, `FlashCapitalEdge`, `LiveCapitalProvider`) | IMPLEMENTED_UNQUALIFIED — reader contracts for Project0/Kamino/NAVI/DeepBook/Scallop exist; effective capacity UNKNOWN | tests/test_dynamic_flash_capital.py |
| 2 | Lender-specific adapters | `src/lending/jupiter_lend.py`, `src/lending/kamino.py` + `kamino_real_conformance.py`, `src/providers/marginfi/`, `src/multichain/sui.py`, `src/multichain/evm_financing.py` | PARTIAL_DECODED / BUILT_OFFLINE_UNQUALIFIED | R-02 CAP-A #602 / CAP-B #612 / CAP-C #609 baselines; TASK_INDEX Track B |
| 3 | Provider candidate catalogue | `src/resources/market_source_catalog.json` (53 rows, 9 families) + `docs/roadmap/r01-r02-live-capital-readers-2026-10-08/PROVIDER_CATALOG.json` (27 candidates) | ALL_DISABLED (`RND_ONLY_27_OPTIONS_ALL_DISABLED_NO_LIVE_CAPITAL`) | catalogue JSON; `source_catalogue.jsonl` (80 rows, 0 enabled) |
| 4 | Quote path | `src/solana_parallel_radar/probes.py` (governed probe owner), P0-2 Jupiter V2/0x owner | IMPLEMENTED_UNBOUND — 0x live capture unbound/authorization-gated | TASK_INDEX completed-baselines table |
| 5 | Route/planner | `src/strategy/arbitrage_graph.py`, `src/strategy/multihop_solver.py`, `src/planning/atomic_marginfi_jupiter.py` | shadow-ready topology; planner owner present | KB map §6 |
| 6 | Sizing | `src/economics/non_monotonic_sizing.py`, `src/economics/split_flow.py` | IN_MAIN (PR118 economics owners) | KB map §5 |
| 7 | Unsigned build | `src/lending/unsigned_builders/`, R-03 contracts #606 | Jupiter/NAVI offline only; Kamino ABI + P0 path blocked | TASK_INDEX Track C |
| 8 | Exact simulation | `src/execution/exact_simulation.py` | IN_MAIN (sender-free simulation/report binding) | KB map §6 |
| 9 | Paper/shadow qualification | `src/paper_shadow/` (incl. `atomic_vertical.py`) | fixture/simulation basis; decision→outcome events MISSING (no EventEnvelope producer — PR #680 trace) | KB map §6; PR #680 §4 |
| 10 | Reconciliation/outcome evidence | `src/observability/store.py` read side (export/replay/metrics) | store-complete, producer-MISSING | PR #680 §4 |

## Source capability modes (static classification)

- `STREAMING`: none wired.
- `POLL_ONLY`: public RPC/catalogued reference feeds (rows with `open-source-rpc-or-host-required` / `public-rate-limited` access classes).
- `ONE_SHOT`: `src/market/native_cpmm_capture.py` — documented one-shot capture without subscriptions; **never report as a real-time stream**.
- `UNAVAILABLE`: all 27 flash-capital candidates (disabled), governed live quote capture (user-authorization gate), runtime decision events (no producer).

## Blocking gates (typed)

| Blocker | Type | Unblocking lane |
|---|---|---|
| No production EventEnvelope producer | `BLOCKED_MISSING_PRODUCER` | OCA-W10 (after W1/W3) |
| Effective flash capacity UNKNOWN | `BLOCKED_LIVE_EVIDENCE_GATE` | R-02 shared live gate (user quorum) |
| Kamino flash ABI unpinned | `BLOCKED_MISSING_PIN` | R03-Kamino |
| 0x live capture unbound | `BLOCKED_AUTHORIZATION` | P0-2-R |
| Orca integration | `BLOCKED_LICENSE_REVIEW` | R-09/R-07 license gate |

## Rules reaffirmed

Catalog rows and adapter presence are not active connectors; builder status never substitutes for capacity evidence; unknown is never zero; LIVE is hard-denied; no signing/sending/borrowing/spending/deployment anywhere on this path.
