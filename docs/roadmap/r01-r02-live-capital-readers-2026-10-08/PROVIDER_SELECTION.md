# Flashloan provider choices — protocol-account cost is not flashloan fee

## Findings / selection
**Primary account-light candidates**
1. **Jupiter Lend — Solana, P0 priority.** Official flashloan API getFlashloanIx returns borrowIx/paybackIx; docs advertise zero protocol fee and no collateral. No separate user marginfi position is shown in flashloan API. HOWEVER signer token ATA, tx fee, rent for missing accounts, program state and borrow limits must be checked. Existing repo's JupiterLendFinancingSnapshot requires fee=0, active flag=false, correct liquidity program and live liquidity.
2. **Kamino Lend — Solana, P0 priority / verify account-free path.** klend exposes flashBorrowReserveLiquidity/flashRepayReserveLiquidity distinct from obligation borrow. These instruction accounts appear not to require user obligation creation for pure flash borrowing, but the latest pinned IDL/SDK, reserve config, instruction index and fee have to be verified. May still require user token accounts and SOL fee payer.
3. **NAVI — Sui, P0 priority.** Official SDK flashloanPTB(tx, coinType, amount) and repayFlashLoanPTB(tx, coinType, receipt, balance) expose no separate lending account-init step. getAllFlashLoanAssets exposes max/flashloanFee/coinType; documentation currently shows zero for many listed assets but also states fees apply and can differ; read the fee for the exact asset, not a protocol-wide constant. Sui gas/object lifecycle remain.
4. **DeepBook V3 — Sui, P1.** borrowBaseAsset/borrowQuoteAsset and corresponding return methods use a pool and PTB loan object; no standalone *flash lender* account-init is described. DeepBook orderbook trading may need a BalanceManager shared object; do not conflate flash-borrow interface with the full arbitrage route setup.

**Conditional / later**
5. **Project 0 (marginfi) — Solana, P1 if account already exists, otherwise explicit opt-in only.** Official Project0Client.createMarginfiAccountTx initializes an on-chain PDA, so a zero protocol flashloan fee DOES NOT remove first-time account setup/rent. On-chain flash requires lending_account_start_flashloan first and lending_account_end_flashloan last, direct transaction not CPI. Use current @0dotxyz/p0-ts-sdk >=2.8.0 per official upgrade guidance; do not use deprecated mrgnlabs client as source of truth. Check bank tag: integrated Kamino/Drift/Jupiter banks are not interchangeable with ordinary borrow-capable banks.
6. **Scallop — Sui, P2.** Documented flash fee 0.1%; verify flash-specific account/obligation requirements and live pool fee/cap. Oracle and Sui gas may add costs.
7. **Cetus — Sui, P2.** Pool-level flash/swap candidate; requires current on-chain pool/package ABI and fee/readback; account setup unknown until verified.
8. **Bucket USDB Flash Mint — Sui, P2.** Synthetic USDB-only, not arbitrary cash asset. Need to confirm current flash-mint fee from SDK/state (historical 0.05% assertion is not treated as proof). USDB -> USDC PSM OUT currently documented 0.30%, separate cost.
9. **Morpho Blue — EVM, next-chain P1.** flashLoan(token, assets, data) advertises fee zero and all singleton token balance. No borrower lending position creation, but an on-chain callback receiver contract is required (deploy it once and reuse; gas still charged). Not an ERC-3156 native function.
10. **Aave V3 — EVM, P2.** No lending position required when repayment is immediate; requires receiver contract. flashLoanSimple fee is NOT waived; flashLoan may waive fee only for approved borrowers. Read current Pool.FLASHLOAN_PREMIUM_TOTAL, do not assume 5 bps remains current.
11. **Balancer V3 — EVM, P2.** Vault unlock/sendTo/settle flow; callback receiver/executor required. Flash fee and allowable tokens/deployments require explicit latest-contract proof.
12. **DODO DVM/DPP/DSP — EVM, research.** Pool-local callback debt, capacity and pool type; no blanket fee/account assertions. Needs deployment audit.
13. **Uniswap V3 — EVM, research.** pool.flash with authenticated callback, fee0/fee1 returned by pool; no lender position creation, but reusable contract must be deployed and gas paid.
14. **Save/Solend — Solana, research.** Reserve flash-borrow candidate. Verify current deployed program, reserve fees, account constraints, support and SDK quality.
15. **ERC-3156 — EVM standard only, research.** NOT a concrete provider. Each implementation must be assessed individually for fee, maxFlashLoan, callable receiver, capital backing and deployment.
16. **Slumlord — Solana, rent sponsor only.** NOT a trading-capital provider; no lender selection as cash flashloan.

## Cost taxonomy to enforce in code
For each candidate produce separate fields:
- needs_lender_position_init: NO / YES / UNKNOWN; must give protocol/code provenance.
- needs_token_ata_or_coin_objects: NONE_VERIFIED / MAY_NEED / REQUIRED / UNKNOWN.
- requires_receiver_contract_deployment: YES / NO / UNKNOWN.
- protocol_flash_fee_model: ONCHAIN_ZERO_VERIFIED / DOCS_ZERO_UNVERIFIED / DYNAMIC_ONCHAIN / UNKNOWN.
- upfront_cost_atoms, rent_refundable_atoms, unavoidable_network_fee_estimate_atoms, funding_asset, unknown blockers. Unknown is not zero.
- preexisting_account_required and optional preexisting_account_address (redacted in public evidence).
- account_origin_fresh=false can be used as a hard qualification policy: never construct CREATE_ACCOUNT/INIT_OBLIGATION/NEW_POSITION/NEW_BALANCE_MANAGER in R-02.

**Zero protocol fee + no new lender position ≠ zero SOL/SUI/ETH required.** No production transaction can promise fully zero expense absent a separately proven sponsor/payer and explicit user authorization.

## Official primary sources
- Project 0 flash: https://docs.marginfi.com/guides/flashloans
- Project 0 account: https://docs.marginfi.com/typescript-sdk/getting-started ; https://docs.marginfi.com/typescript-sdk/accounts
- Project 0 bank/integrations: https://docs.marginfi.com/typescript-sdk/integrations
- Project 0 fees and SDK version: https://docs.marginfi.com/protocol-overview/fees ; https://docs.marginfi.com/typescript-sdk/overview
- Jupiter Lend flash: https://developers.jup.ag/docs/lend/flashloan ; https://developers.jup.ag/docs/lend/flashloan/execute
- Jupiter Liquidity read SDK: https://developers.jup.ag/docs/lend/liquidity/analytics
- Kamino official klend: https://github.com/Kamino-Finance/klend ; https://github.com/Kamino-Finance/klend-sdk
- NAVI SDK: https://sdk.naviprotocol.io/lending/flashloan
- DeepBook Sui: https://docs.sui.io/onchain-finance/deepbook/deepbookv3-sdk/flash-loans
- Scallop fee: https://docs.scallop.io/protocol/fee
- Bucket PSM: https://docs.bucketprotocol.io/mechanism/usdb-peg
- Morpho Blue: https://docs.morpho.org/developers/contracts/blue/ ; https://docs.morpho.org/learn/concepts/flashloans/
- Aave: https://aave.com/docs/aave-v3/guides/flash-loans
- Balancer Vault: https://github.com/balancer/balancer-v3-monorepo/blob/main/pkg/vault/contracts/Vault.sol
- Uniswap V3: https://developers.uniswap.org/docs/protocols/v3/guides/flash-swaps/getting-started
- Save: https://docs.save.finance/architecture/user-instructions


## New options from official source audit, do not enable by default
- **Euler EVault**: `flashLoan(uint256,bytes)`, usually zero base flash fee; vault hooks can add cost/limits. Receiver contract needed. New viable EVM expansion candidate.
- **Uniswap V2 flash swaps**: optimistic pool swaps, nonzero fee; callback contract needed; pool reserves shared with trading liquidity.
- **Uniswap V3 and PancakeSwap V3 pool.flash**: explicit callback repayment fees. Callback must verify factory/pool.
- **Balancer V2** separate from V3: traditional `Vault.flashLoan` callback, whereas Balancer V3 uses `unlock/sendTo/settle`; different ABI.
- **Silo V2**, vault-configured `flashloanFee`, hooks may restrict eligibility.
- **Instadapp Flashloan Aggregator**: route chooser `getBestRoutes`; must deduplicate underlying Aave/Balancer/etc. This adds a funding *route*, not new independent capital.
- **SparkLend** separate Aave-style pool (historic zero fee is NOT current proof), **Fluid DEX V2** flash-accounting without a verified cash lender, **Suilend** user-facing flash behavior but no pinned standalone SDK — keep research-only.
- **PancakeSwap V2** and **Maker DSSFlash** included as unverified research placeholders, not enabled providers. 
- Save/Solend remains blocked by official docs warning. `ERC-3156` is only a standard; `Slumlord` only rent assistance.

See `offline/SOURCE_LEDGER.json` for exact official links/SHAs and each confidence grade, and `offline/*_PROTOCOL_DOSSIERS.md` for self-contained integration notes. Always prioritize no new lender position, but never confuse with zero gas/ATA/receiver deployment costs.
