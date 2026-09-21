# MEGA8-07 — Performance, distributed evidence and governed capital mechanisms

Implementation base revalidated on current main: `1605418661bb4571fcdf7aeaeb3c964087275dc3`.

## Scope

This branch implements **PR-271–PR-286 / NF-769–NF-832 only** as an
offline/default-off research and control-contract layer.

- PR-271–278: Rust/vector/GPU parity contracts, immutable state cache,
  deterministic distributed research scheduling, event-time joins, cold archive
  manifests and lineage catalog.
- PR-279–286: finalized-profit reinvestment, wallet-role segregation,
  conservative lender-capacity forecasting, non-atomic margin, lending-rate
  research, stablecoin stress, term-structure research and cross-protocol
  liquidation portfolio contracts.

## Anti-duplication / canonical reuse

MEGA8-07 does not replace these existing authorities:

- `src/research/common.py`: offline research/effect boundary.
- `src/economics/capital.py` and durable reservation owners: executable
  capital and wallet-cost authority.
- `src/lending/controlled_expansion.py`: lender qualification.
- `src/security/supply_chain.py`: dependency/supply-chain release gate.
- `src/inventory/non_atomic.py`: non-atomic inventory risk domain.
- `src/liquidation/planner.py`: liquidation instruction planning.
- existing signer/submission/release owners remain untouched.

The new package has no HTTP/RPC client, private-key handling, signing,
submission, subprocess execution, real Rust/GPU invocation, remote cache,
distributed worker, object-store write, wallet transfer, or capital mutation.

## Dependency truth

The eight-pack roadmap names MEGA8-01..06 as prerequisites. All six are now merged
and their dependency evidence is resealed on closure baseline
`613884d8a5d50b1230b29ec5db14627222a9e85d`. MEGA8-07 itself merged after
MEGA8-04, so no MEGA8-07 implementation inversion remains.

Repository-internal code status remains `IMPLEMENTED_OFFLINE`. Operational status
is `BLOCKED_EXTERNAL_AND_PROMOTION_EVIDENCE` because real accelerator/distributed
infrastructure evidence and any capital/wallet/margin/credit/liquidation promotion
must still pass their existing authorities. Dependency reconciliation does not
grant production readiness, live authorization or capital permission.

## Child ownership

| Child | NF | Owner |
|---|---|---|
| PR-271 PERF-01 | NF-769–772 | `src/mega8_07/pr271.py` |
| PR-272 PERF-02 | NF-773–776 | `src/mega8_07/pr272.py` |
| PR-273 GPU-01 | NF-777–780 | `src/mega8_07/pr273.py` |
| PR-274 CACHE-02 | NF-781–784 | `src/mega8_07/pr274.py` |
| PR-275 DIST-01 | NF-785–788 | `src/mega8_07/pr275.py` |
| PR-276 STREAM-02 | NF-789–792 | `src/mega8_07/pr276.py` |
| PR-277 ARCHIVE-02 | NF-793–796 | `src/mega8_07/pr277.py` |
| PR-278 CATALOG-01 | NF-797–800 | `src/mega8_07/pr278.py` |
| PR-279 CAPITAL-04 | NF-801–804 | `src/mega8_07/pr279.py` |
| PR-280 WALLET-02 | NF-805–808 | `src/mega8_07/pr280.py` |
| PR-281 CAPITAL-05 | NF-809–812 | `src/mega8_07/pr281.py` |
| PR-282 MARGIN-01 | NF-813–816 | `src/mega8_07/pr282.py` |
| PR-283 CREDIT-01 | NF-817–820 | `src/mega8_07/pr283.py` |
| PR-284 STABLE-02 | NF-821–824 | `src/mega8_07/pr284.py` |
| PR-285 TERM-01 | NF-825–828 | `src/mega8_07/pr285.py` |
| PR-286 LIQ-04 | NF-829–832 | `src/mega8_07/pr286.py` |

## Upstream / source-copy disposition

No external source is copied, ported, vendored, installed or executed. PyO3,
maturin, petgraph, rayon, NumPy/Numba/GPU libraries, NATS/Redis, Ray/Dask/Celery,
Bytewax, fsspec/object stores and protocol SDKs remain REFERENCE/DEPENDENCY/TOOL
candidates pending immutable pin, license, conformance and benchmark evidence.

## Verification

Dedicated tests cover exact 16-child/64-function ownership, banned effectful
imports, negative/replay invariants and representative contracts for every child.
The workflow performs installed-package smoke, compile, Black, structural
verification, focused tests and regressions for current capital/lender/liquidation
owners.

## Rollback

Revert/disable `src/mega8_07/`, coverage/docs/workflow and tests. There are no
started external operations to recover. Retain append-only coverage/evidence for
audit.
