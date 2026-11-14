# Current repository owner map — reuse these canonical responsibilities

Audited against main `86be458a87ed3f499cc32ff56426b2866c90422a` and current tree/code paths. A path existing or a class compiling does not prove a supported boot path, live source, current external ABI or market qualification.

| Responsibility | Canonical owners in main | What agents must not create |
|---|---|---|
| Source admission, quotas, evidence | `src/qualification_campaign/`, `src/provider_governance/`, `src/market/streams.py`, `src/solana_parallel_radar/`, `src/gpr_sui_shadow/` | Another source-governance scheduler, rate ledger, RPC quorum or evidence journal |
| Canonical asset identity | `src/assets/resolution/`, `src/resources/asset_mint_registry_pr117.json`, GPR AssetRegistry/provenance | Ticker-to-mint registry or a second alias resolver |
| Market discovery/lifecycle | `src/market/discovery.py`, `src/market/source_catalog.py`, `src/discovery/dynamic_universe/`, `src/research_economic_graph/` | Another universe catalogue, source catalogue or market graph |
| Market relations/correlation | `src/strategy/relation_generators/`, `src/research/correlation_ledger/` | Another relation graph or pair-correlations DB |
| Strategy search/ranking | `src/strategy/strategies.py`, `src/strategy/registry.py`, `src/strategy/arbitrage_graph.py`, `src/strategy/multihop_solver.py`, `src/strategy/ranker.py` | A second strategy registry, arbitrage graph or solver |
| Economic sizing | `src/economics/non_monotonic_sizing.py`, PR118 sizing/split-flow owners | Linear quote multiplier or another sizing engine |
| Venue state/direct adapters | `src/direct_venue/`, `src/providers/raydium_cpmm_native.py`, `src/market/native_cpmm_capture.py`, `src/providers/orderbook/`, `src/multichain/` | Duplicate universal DEX decoder or untracked SDK copy |
| Flash capital | `src/economics/flash_capital_graph/`, `src/lending/`, `src/providers/marginfi/` | New lender registry/flash-capital graph/ledger |
| Financing and unsigned plan | `src/lending/agg03_financing_ports.py`, `src/lending/financing.py`, existing planner/unsigned contract owners | Protocol-specific parallel transaction kernel |
| Exact simulation | `src/execution/exact_simulation.py`, existing finalizer and evidence owners | Simulation service that bypasses authority/evidence |
| Paper qualification | `src/paper_shadow/`, `src/qualification_campaign/`, durable paper lifecycle | Another paper journal or manually promoted result |
| Liquidations | `src/liquidation/` and protocol readers | Revival of quarantined legacy liquidation sender |
| Strategy evolution | `src/strategy_evolution/` (9 packages; all DISABLED); `docs/strategy_evolution/` | Another ML/anomaly/strategy-evolution registry |
| Stable peg math | `src/strategies/stable_peg/` | A duplicate band/stableswap math library |
| Runtime/authority | `src/runtime/`, `config/capabilities.json`, `src/resources/runtime_authority.json`, QPR release authority | Any second execution gate, signer or sender path |

## Current strategy capability truth
- `src/strategy/strategies.py`: circular strategy uses a two-leg detector; LST strategies are shells; orderbook/AMM is disabled pending verified subscriptions; Pump migration emits no heuristic opportunities.
- `src/strategy/multihop_solver.py`: bounded route shortlist + exact evaluator interface; the shortlist alone is not exact output or profitability.
- `src/strategy_evolution/`: nine packages, all `DISABLED`, allowed only OFFLINE/PAPER/SHADOW and qualify at most `VERIFIED_SHADOW`. The architecture is sender-free.
- `src/liquidation/strategy.py`: shadow liquidation reconciler/planner; not a sender.
- `src/strategies/stable_peg/`: reusable exact band math exists and is reused by `src/direct_venue/super03.py`.
- `src/direct_venue/mpr2617.py` and `super03.py`: conformance/evidence models, not proof every venue read/quote is live.

## Core data-domain separation
1. Asset identity (canonical token/mint/type and economic representation).
2. Market/pool/book identity (factory/program/package + pool/book ID + fee tier/hooks + underlying resource).
3. Market state (slot/checkpoint/block/root, account/object versions, vault/book/ticks/bins).
4. Quote (amount/direction, exact output/fee/rounding/partial-fill semantics).
5. Capital resource (lender + per-asset reserve/bank/pool + borrow cap/fee/repay constraints).
6. Builder contract (unsigned instruction/PTB, exact ABI and order).
7. Full simulation (complete same-domain transaction/PTB and postconditions).
8. Paper evidence and statistical qualification.
These evidence domains must not be collapsed to one `verified=true` flag.
