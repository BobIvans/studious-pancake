# R-02 — concrete Live Capital Readers (read-only)

## Outcome, not a second engine
Build evidence-rooted **real on-chain bank/reserve/pool snapshots** for P0/Project 0, Jupiter Lend, NAVI, Kamino; optional DeepBook pool snapshot as separate P1. Reuse FlashCapitalGraph/LiveCapitalProvider and QPR evidence owners. R-02 ends at capital discovery/refresh, not borrowing, creating accounts, signing or submitting.

## Independent contracts and responsibilities
1. Chain read transport = existing governed QPR read-only transport + slot/checkpoint and source generation, physical rate quotas, operator grouping, max payload, deadlines, retries, negative evidence, hashed public redacted capture and deterministic offline replay.
2. Protocol bridge = pinned official SDK/package/IDL decoder -> validated raw snapshot(s), not opaque SDK object serialized and trusted.
3. Normalizer = atom integers and rational fees, explicit mint/coin type/resolver generation, reserve/pool identifier and flash eligibility. On semantic drift produce typed negative evidence; do not coerce floats.
4. Capital graph adapter = existing FlashCapitalEdge + injected LiveCapitalProvider (payload, Evidence). Do not add a new alternative capital graph.
5. Evaluator = separate account/rent/setup economics and flash fee, capacity/fee freshness; no authority to promote source observations to exact execution.
6. Adapter outputs are unsafe for R-03 builder until protocol and full-message simulation have independent evidence. preserve global sign/send false.

## Specific current code integration gap
src/economics/flash_capital_graph/graph.py has provider whitelist {project0, marginfi, kamino, navi, deepbook, scallop} and matching chain checks, but **NO JupiterLendCapitalProvider**. Extend it narrowly to provider id jupiter_lend/solana with explicit coverage, fixture validation and no change to existing Project0/Kamino/NAVI edge identity semantics. Reuse src/lending/jupiter_lend.py for FlashloanAdmin Borsh layout and src/lending/agg03_financing_ports.py for financing snapshot facts; do not fork ABI. JupiterLendFinancingSnapshot explicitly rejects active/paused/non-zero-fee conditions, so R-02 must faithfully represent them as BLOCKED, even if marketing says fee 0.

## Common snapshot schema (proposal; adapt as an additive versioned extension)
One positive normalized observation must contain:
- schema: dynamic-universe.capital.v1 (existing graph adapter), provider, chain, observation_id, evidence binding to QPR authority and SourceDossier, source_commit/sdk_version/idl_hash, genesis/network, program/package ID, resource_id (bank/reserve/pool), canonical_identifier (Solana mint incl token program policy, or Sui full coin type), resolver_generation.
- slot_or_checkpoint, observed_at_ns, max_staleness_slots_or_checkpoints, state_root_or_verified_digest, RPC endpoint identity and independent quorum status; resource owner proof, source hashes and raw payload hash.
- flash_enabled (bool), max_amount_atoms (integer exact), fee_numerator, fee_denominator (rational), protocol_rounding_atoms (integer), constraints (list), mutable flags, relevant liquidity vault/limit/protocol fee fields, each decoded from documented pinned layout.
- needs_lender_position_init, token_account_setup_cost_status, network_fee_not_borrowed, account_cost_source_proof, fee_source_proof, capacity_source_proof; distinguish UNKNOWN from ZERO.
- negative_observation object for rejection and replay (no edge created when negative, stale, unsupported or uncertain).

Keep payload schema 100% compatible with the existing consumer, or introduce a versioned pre-normalization envelope feeding existing format. Never silently invent fields required by the graph.

## Adapter slices, in recommended order

### R02-A: Jupiter Lend — **first**
- Fetch exact program admin PDA through governed RPC and decode via existing decode_flashloan_admin_state.
- Resolve flash-loan token reserve-liquidity from pinned official protocol account graph, not from API name alone. Verify token mint, program owner, source account, token program, decimals, liquidity contract state, status/paused/active and any per-token caps.
- Reuse JupiterLendFinancingSnapshot constraints; flashloan fee may be advertised 0 but only on-chain admin state proves this snapshot. Negative if fee != 0 until zero-only financing port is deliberately audited.
- Compute spendable available flash amount as minimum of supported proven limits; physical vault balance is only one input. Unknown borrow ceiling/reserve reservations => BLOCKED (not pretend whole balance).
- No MarginfiAccount creation, no position NFT. For future builder, enforce local ATA existence or separately priced creation; SDK getFlashloanIx supports borrow->custom->payback. This R-02 work issues no instructions.
- Deliver 2+ positive *real* observed token resources only if protocol state supports them, plus paused / active / wrong owner / fee nonzero / missing ATA / staleness negatives. A real read returning zero qualified assets is a valid honest result.

### R02-B: Kamino — **second**
- Pin official klend and @kamino-finance/klend-sdk versions/commit, current program id and relevant deployed markets. Via KaminoMarket.load + loadReserves and validated RPC account owner read.
- Distinguish user obligation borrowing from separate flashBorrowReserveLiquidity/flashRepayReserveLiquidity pair. Verify the current flash ABI requires no user obligation; record result YES/NO/UNKNOWN with source hash. Do not initialize obligations or farms for R-02.
- Parse reserve liquidity, flash configuration, outstanding/reserved amounts, borrow enable flags, oracle health, fee and flash instruction compatibility. If fee or limit cannot be independently decoded from a pinned layout, return typed negative; do not substitute regular borrow APY or loan origination fees.
- Record reserve -> mint -> liquidity vault proof; reject stale market/reserve mismatch, vault balance-only extrapolation, Token-2022 unsupported variants.
- Reuse src/lending/kamino.py and kamino_real_conformance.py, not a duplicate Kamino protocol registry.

### R02-C: NAVI — **third**
- Use official @naviprotocol/lending getAllFlashLoanAssets({env:'prod',cacheTime:bounded}) and getFlashLoanAsset where necessary. Correlate SDK max/flashloanFee/coinType with current Sui shared-pool object state and reviewed full CoinType/package IDs.
- Exact decimals from reviewed Sui metadata; treat SDK decimal strings explicitly, never JS IEEE754 floating point. The existing navi_sdk_snapshot demands string max and flashloanFee, resource_id, flash_enabled, protocol_rounding_atoms and constraints; implement strict SDK mapper and reject missing provenance.
- Root by chain/checkpoint and configured GraphQL/approved fullnode clients; do not reactivate legacy JSON-RPC if retired by DIN-02. An API live table alone is NOT a rooted capital snapshot.
- No obligation/user account creation for the flash PTB based on official helper shape, but verify coin selection, gas coin, receipt repayment and any storage object costs. Full PTB stays R-03.

### R02-D: Project 0 — **fourth, conditional**
- Use official @0dotxyz/p0-ts-sdk >=2.8.0 and fresh dynamic banks/client metadata, filtered by Default asset tag, bank status, mint, borrow/flash limits and oracle health. Integrated Kamino/Drift/Jupiter wrapper banks must not silently become fresh flash borrowing sources.
- Verify existing marginfi account exists using getAccountAddresses/fetchAccount in read-only mode (optional wallet public key). If none exists, emit ACCOUNT_INITIALIZATION_REQUIRED and NO eligible account-light edge. Never call createMarginfiAccountTx or assume fees=0 implies rent=0.
- Enforce direct lending_account_start_flashloan first (after compute budget) and lending_account_end_flashloan last, never CPI, no nested flashloans. R-02 records capability and costs only; builders later.
- If bank state supports a valid 0 protocol fee, distinguish that from account-init and token-ATA/rent setup.

### R02-E optional: DeepBook pool capacity (P1 after four core slices)
- A live shared pool balance and its borrowable base/quote amount, flash fee/protocol rules, checkpoint proof and contention with orderbook liquidity. Compare pool flashborrow path vs route requiring BalanceManager creation; keep them separate.
- No new BalanceManager as an R-02 side effect. Competing orderbook liquidity can make naive pool-balance capacity wrong.

## Quota + refresh algorithm
- Poll only shortlisted capital hubs and route-selected assets, not every research-universe asset per tick. Startup discover market IDs + static pins; batch/multiget when supported. Deduplicate subscriptions by on-chain account/package/resource.
- Reuse DIN-00 operator quota; failed reads count as physical attempts. No invented unlimited RPC; explicit per-source budgets, backoff and 429 cooldown.
- TTL configurable per chain/source, enforced by slot/checkpoint comparison at selection. Never transform a recently fetched off-chain cache value into fresh chain evidence. RPC quorum cannot be two endpoints routed to one operator.
- Read snapshots persist canonical serialized bytes/hash, source, endpoint, chain head, time, slot, negative outcome; bounded retention and redaction. On replay no external requests. Preserve QPR provenance/generation constraints.

## No-rent-account admission gate
Before any lender enters preferred shortlist: (a) must have proven no *new lender position* required for flash borrowing, (b) known full route's ATA/gas/receiver setup expense or explicitly UNKNOWN, (c) current flash fee/capacity evidence, (d) asset identity + simulation compatibility. Existing-account-dependent P0 may remain visible with blocked reason and opt-in strategy, not deleted from research graph.

## Output contracts
- src/... small protocol readers & targeted tests; exact directories selected by Codex after code-owner audit.
- read-only typed snapshot edge/negative evidence; readable provider ranking and setup-cost profile.
- one bounded live observation per core provider if source access works; if not, zero positive edges + recorded authentic network/auth blocker.
- deterministic replay fixture for each adapter, tested with network disabled.
- end-of-R-02 report with current SHA, exact tests, per-provider capabilities, account-init verdict, fee source, slots/checkpoints and no live authority.
