# Assignment — R-07 additional flash-capital provider qualification

Copy/paste trigger: Expand flash-capital coverage without changing the maximum research universe or duplicating the execution engine. First audit the merged 27-candidate catalog, provider source ledger, cost selector, current FlashCapitalGraph allowlist and per-chain capability registry. Select one provider per implementation PR based on a real route/settlement gap, independent capital resource, source/API/SDK pin, deployability and account/setup cost. Do not implement a catalog in one large batch and do not enable any provider by default.

## Candidate groups to reassess
- Sui: Bucket/USDB flash mint, Scallop, Cetus, DeepBook and other providers with current deployed package/object proof.
- EVM: Morpho Blue, Aave V3, Balancer V2/V3, DODO, Euler, Silo, Uniswap V2/V3 flash mechanisms and concrete ERC-3156 implementations.
- Solana: Project 0, Kamino, Jupiter Lend, Save/Solend only where exact currently deployed flash semantics and account costs are proven.
- Wrappers/aggregators such as Instadapp are route selectors, not independent capital resources; deduplicate their underlying lender liquidity. ERC-3156 is a standard, not a lender. Slumlord is rent-only assistance, not trading capital.

## Per-provider qualification checklist
1. Official protocol docs + pinned source/SDK/IDL/ABI version, exact license and transitive dependencies.
2. Chain genesis/chain ID, deployed program/contract/package ID and bytecode/source attestation.
3. Resource identity: reserve/pool/vault/singleton/contract balance; token/coin mint, decimals and actual available capacity.
4. Exact fee model, rounding, governance mutability, max amount, pause/status flags, liquidity and debt constraints.
5. Atomic repayment/callback/hot-potato semantics; required receiver code/deployment, account/position/ATA/coin objects, gas and rent.
6. Independence and shared-resource correlation groups; no double-counting between lenders, routers and venues.
7. Bounded real read evidence, deterministic replay, positive and negative tests, typed blockers.
8. R-02 reader proof, R-03 unsigned builder proof, then R-05 exact simulation before inclusion in any qualified route.

## Selection principle
Choose providers by incremental executable opportunities and all-in net economics, not by TVL or token count. A zero flash fee does not mean zero cost; an aggregator does not create liquidity; an ordinary borrow market is not necessarily flash-borrowable.

## Deliverable
One review-only PR per provider with a source dossier, status row, reader/builder owners, exact tests/replay, current capacity/fee evidence, supported assets and amount limits, upfront/setup cost taxonomy, shared-resource identity and explicit disabled-by-default status. No signing, sending, borrowing, receiver deployment or production promotion.
