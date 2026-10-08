# Cheapest *usable* capital, not merely cheapest flash protocol fee
This is the offline design contract for later R-04; R-02 produces observations only. The bot should choose among all **verified** lenders for the user's arbitrage route, not be hard-wired to Project 0. No chain-crossing atomicity: Solana atomic flash funds only a Solana transaction, Sui flash funds only a single PTB, EVM only a local EVM transaction.

## A. Four independent cost classes
1. New protocol-specific lender account/position: e.g. Project 0 marginfi PDA `createMarginfiAccountTx`. If the position does not exist and user budget forbids creation, HARD BLOCK no matter how cheap flash fee is.
2. Token accounts/storage: Solana ATA or WSOL creation/rent (some accounts refundable only on safe close); Sui gas coins/coin objects/storage; EVM allowance and **receiver smart contract deployment** when no existing audited receiver. UNKNOWN ≠ zero.
3. Flash principal and protocol charge: amount borrowed repaid *within the same atomic transaction*, plus exact fee rate/rounding from protocol current state. Zero in docs is discovery only until decoded state validates it; the P0/Jupiter marketing condition does not make wrong on-chain fee a success.
4. Execution costs: DEX venue fee (already inside quote? mark included), token transfer fee, priority fee, block-engine/Jito tip, slippage, Sui gas, EVM gas, revert/failure reserve. Abort if not provably bounded under user's separate budget.

## B. Live CapitalOffer (a proposed projection, never new authority)
~~~
{
  "chain": "solana|sui|evm",
  "provider_id": "...",
  "underlying_liquidity_source_id": "...",
  "asset_canonical_id": "...",
  "resource_id": "bank|reserve|pool|vault",
  "observed_at_slot_or_checkpoint": "...",
  "capacity_atoms": "exact integer",
  "fee_numerator": 0,
  "fee_denominator": 1,
  "fee_rounding_rule": "up|verified_protocol",
  "position_init_required": "NO|YES|UNKNOWN",
  "position_already_exists": "true|false|unknown",
  "token_account_cost": "verified atoms or UNKNOWN",
  "contract_deployment_cost": "verified native gas or UNKNOWN",
  "gas_or_network_fee_estimate": "verified conservative bound or UNKNOWN",
  "total_unavoidable_upfront_spend_atoms": "verified exact bound or UNKNOWN",
  "quote_venue_fee_included": "true|false|unknown",
  "evidence_refs": ["..."],
  "source_generation": "...",
  "execution_authority": "NONE"
}
~~~
Do not actually emit as exact capital graph edge unless original evidence/schema/owner validators accept it. Use a versioned intermediate projection to existing `FlashCapitalEdge` with all required current fields.

## C. Fail-closed selection algorithm for R-04
Input: research graph candidate + route + requested chain + asset(s) + sizes + wallet's **public** preexisting account inventory + user-approved budget of transaction token (SOL/SUI/ETH; 10 EUR budget is not a substitute for exact native unit balance) + current verified protocol states.

1. Restrict to one chain/local atomic context and matching canonical assets/token programs/coin types. Cross-chain correlation may inform candidate research but never compose one cross-chain flashloan.
2. Candidate's protocol source and upgrade/deployment provenance must be admitted. If any of owner/mint/ABI/fee/cap/slot unavailable, record a typed negative and **exclude**.
3. Apply account policy: `NO_NEW_LENDER_POSITION`; reject `position_init_required==YES` unless `position_already_exists==true`. Reject UNKNOWN unless the user explicitly chooses a research-only inspection (still no execution).
4. Apply token account and receiver contract cost: `existing_ATA_or_receiver` is different from `does_not_require_lender_position`. If setup/new ATA/deployment cost unknown, do not label `zero_upfront`; keep as NEEDS_SETUP_PROOF.
5. Project P0 integration bank tags: do not assume flash borrowing. Kamino reserve fee/flash-enable and Jupiter admin fee must be decoded. For NAVI max and fee require actual Sui pool/checkpoint; DeepBook shared pool capacity does not permit concurrent double claims.
6. Obtain amount-dependent `min(proved_vault_cash, limit_remaining, caps, token_transfer_constraints, lock_reservations)` and exact protocol fee with correct atom rounding. Unknown component => cap unknown, no positive edge.
7. Deduplicate physical origin: Instadapp + Aave same actual pool, multiple RPC endpoints of one operator, or overlapping route/capital pool are a single liquidity resource; don't sum capacities. Group by `underlying_liquidity_source_id`.
8. Compute bounded end-to-end gross and net route economics: repayment + exact flash fee; DEX fee only if not already included in quoted output; network/gas, priority/Jito tips, ATA storage setup, receiver amortization only if already deployed, slippage reserve, failure risk. Unknown input => no net-profit claim.
9. Use existing `src/economics/non_monotonic_sizing.py` to search profitable size windows (do not assume larger is better). Use existing `FlashCapitalGraph` and exact simulation; do not create second selection engine.
10. Rank by **verified simulated net return subject to capped upfront spend**, with tie-breakers older/better evidence, lower protocol+network fees, fewer writable account locks, smaller tx bytes/compute, fewer setup side effects. Never rank by marketed '0% fee' alone.

## D. UI/manifest classes for provider chooser
- `NO_LENDER_POSITION_PUBLISHED` (Jupiter, Kamino, NAVI, DeepBook): read-only candidates; NOT yet 'zero upfront'.
- `EXISTING_ACCOUNT_ONLY` (P0): selectable only if actual existing marginfi account is proven, otherwise blocked with setup warning.
- `CALLBACK_CONTRACT_REQUIRED` (Morpho, Euler, Aave, pool flash swaps): enabled only after a reusable audited receiver exists or deployment cost is separately authorized.
- `FLASH_SWAP_POOL` (Uniswap V2/V3, Pancake V3, DODO): route-dependent fee and capacity; pool price impact/quote relationship must be modeled.
- `SYNTHETIC_MINT_ONLY` (Bucket): USDB is not equivalent to USDC; PSM exit fee distinct.
- `AGGREGATOR_NOT_UNIQUE_LIQUIDITY` (Instadapp): can choose best underlying lender, but don't add independent liquidity.
- `RESEARCH_OR_BLOCKED` (Save, Suilend, fluid flash accounting, Maker, etc.): no live-capital edges.

R02 reader PRs may store above cost-status observations, but `sign_enabled=false,send_enabled=false` throughout and offer IDs are NOT execution permits.
