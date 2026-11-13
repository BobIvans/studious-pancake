# Assignment — R-04 Capital-aware universal route selector

Copy/paste trigger: Implement R-04 only after current-main exact quote/state owners and at least one R-02 lender reader plus its R-03 unsigned builder have passed their own gates. Audit current UniversalArbitrageGraph, bounded multihop solver, relation generators, quote providers, FlashCapitalGraph, PR118 nonlinear sizing, cost ledger and existing atomic planner. Design the smallest integration that chooses among exact route + settlement asset + lender + amount combinations. Do not create another graph, route solver, quote plane, capital ledger or execution kernel.

## Required behavior
1. Ingest only canonical asset identities and amount-specific quote/state evidence. Indexed pool metadata, ticker links and correlations can generate discovery relations but cannot become executable edges.
2. For each single-chain atomic route, enumerate eligible lender edges for its settlement asset. The route target asset does not itself need flashloan support.
3. Evaluate provider, resource and exact principal together. Refresh capacity/fee evidence for the proposed amount; never scale a quote or capacity linearly unless the source contract explicitly proves that rule.
4. Use PR118 non-monotonic amount grids. Re-quote each candidate amount and recompute exact DEX fee, price impact, transfer tax, lender premium/rounding, repayment and all account/network costs.
5. Model separate cost terms: flash premium; protocol/DEX fees; Token-2022 transfer fees/hooks; network/base fee; compute/priority fee; Jito tip if actually enabled; rent/ATA/coin-object costs; EVM gas/receiver deployment; Sui gas/object constraints; sponsor eligibility. Unknown is not zero.
6. Deduplicate common capital resources and shared pool liquidity. A lender and a DEX using the same vault/pool must not count the same atoms twice. Aggregator/router results are quote sources, not independent underlying liquidity.
7. Enforce same-chain / same-transaction atomicity. TON asynchronous routes and cross-chain bridge paths remain separate research/economic classes unless their local atomic settlement semantics are separately proven.
8. Rank conservative net output only after exact amount quote, repayment coverage, resource lock constraints, instruction/account limits and current capital snapshot checks. Include worst-case safety buffer and explicit rejection reason.

## Evidence / acceptance
- A normalized candidate carries route ID, exact source/target mints, route quote fingerprints, lender/resource identity, requested amount, fee/repayment, state slot/checkpoint, cost breakdown, size grid and source provenance.
- Negative cases: no eligible lender; stale capacity; fee drift; borrow cap; shared resource double count; amount quote unavailable; route uses different chain; setup/gas unknown; repayment underfunded; non-monotonic profit curve; provider disagreement.
- Deterministic offline replay and integration tests reuse existing owners. No fixture can produce live capital status.
- Paper/unsigned output only. Do not wire a signer/sender or mark a route live-ready.

## Deliverable
One small review-only PR with an architecture diagram, owner reuse matrix, candidate receipt schema, tests, replay command, before/after route-selection examples and exact blockers.
