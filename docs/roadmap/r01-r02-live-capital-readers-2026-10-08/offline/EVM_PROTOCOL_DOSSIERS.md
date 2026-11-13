# EVM account-light flash liquidity — offline technical dossiers
Audited 2026-10-08. EVM callback deployment and runtime gas make these future R-07 candidates for a 10 EUR testing budget. Read-only research can be done sooner; do not promote to Solana/Sui R02 core.

## Morpho Blue — high-priority later, zero protocol flash fee
Official https://docs.morpho.org/developers/contracts/blue/ and morpho-org/morpho-blue@8e26ca6a8dbc5089edcd67fb576248810fd2870a.
- `flashLoan(address token, uint256 assets, bytes calldata data)`, calls `onMorphoFlashLoan` on caller; no borrower credit position required; docs say `flashFee=0`.
- Max is token's **entire balance in Morpho Blue singleton contract**, not any single Morpho market available-to-borrow number. Source balance and token constraints need chain-specific deployed contract proof.
- Must use an authenticated, existing or deployed callback receiver contract; no free arbitrary EOA execution. One-time contract deployment requires gas unless reused/sponsored. Morpho native flashloan is NOT directly ERC-3156 compliant.

## Euler EVK — additional strong EVM candidate
Official https://docs.euler.finance/build/evk/interacting-with-vaults/ and https://docs.euler.finance/curate/vaults/evk/hooks-custom-logic/, pinned repo euler-xyz/euler-vault-kit@e88274cc624b9867d3c0197614dc5fe5201377c3.
- `EVault.flashLoan(uint256 amount, bytes data)`; authenticated borrower callback `onFlashLoan(bytes)`; repay underlying balance within same EVM transaction.
- Core normally has no flash fee, **but installed hooks can impose fee, eligibility restriction, pause or utilization cap**. Do not create generic zero-fee provider for every vault. Read each deployment's asset, balance, factory, hook receiver, fee checks, callback auth. Requires reusable callback contract.
- Every vault is a separate flash liquidity resource; do not double count the same underlying liquidity if wrappers/proxies share it.

## Aave V3 and SparkLend — Pool semantics, deployment-specific fee
Official https://aave.com/docs/aave-v3/guides/flash-loans
- `flashLoanSimple(receiverAddress,asset,amount,params,referralCode)` one asset, requires callback contract `executeOperation` and approval/repayment. `flashLoan()` multi-asset, approved `flashBorrowers` may have fee waiver ONLY on this variant.
- Fee initialized 0.05% historically, governance adjustable; **read current Pool.FLASHLOAN_PREMIUM_TOTAL** and per-reserve flash-enabled flags. A public borrower cannot assume whitelist status.
- SparkLend is a distinct deployed Aave-style pool with independent liquidity; an old deployment verification noted zero initial fee, NOT proof current fee remains zero. `SparkLend` requires current deployment address, pool premium, reserve flags, runtime health. Treat research until independently audited.

## Balancer V3 AND Balancer V2
- V3 official https://github.com/balancer/balancer-v3-monorepo/blob/main/pkg/vault/contracts/Vault.sol: `unlock(bytes)`, `sendTo(token,to,amount)`, transfer repayment, `settle(token,amountHint)` and zero non-settled deltas by end of unlock callback. This is **not the V2 flashLoan(receiver,tokens,amounts,userData) interface**. V3 fees and specific deployment restrictions must be confirmed on-chain.
- V2 official https://github.com/balancer/docs-developers/blob/main/resources/flash-loans.md: explicit `Vault.flashLoan` + `receiveFlashLoan` callback; different source/config and liquidity. Keep separate adapters if later qualified.

## Silo V2/V3 — flashLoan per vault, configurable fee
Official https://docs.silo.finance/docs/developers/dev-tutorials/hooks/ and /silo-config/. Docs expose Flash Loan hook with receiver, token, amount, fee; deployment configurations include `flashloanFee`. Silo v2/v3 naming/deployments matter. Requires callback contract and vault-specific source/fee proofs, not universal 0. Future R-07 only.

## Uniswap V2 — flash swap, NOT generic lending reserve
Official https://developers.uniswap.org/docs/protocols/v2/concepts/flash-swap. Pair.swap(amount0Out,amount1Out,to,data) permits optimistic token transfer and callback before settlement; repay returned asset + applicable pair swap fee OR pay other leg while preserving invariant. Reserve-specific, pool fee nonzero. Requires pair authentication and callback receiver. Liquidity is the trading pool itself: avoid double counting quote liquidity and lender capacity as independent.
## Uniswap V3 — pool-local `flash`
Official https://developers.uniswap.org/docs/protocols/v3/guides/flash-swaps/getting-started, /flash-callback. `pool.flash(recipient,amount0,amount1,data)` with `uniswapV3FlashCallback(fee0,fee1,data)`, verified canonical pool/factory, repay fee0/fee1. Receiver contract and gas required. Different ABI from Uniswap V2, no shared generic builder.
## PancakeSwap V3
Official https://github.com/pancakeswap/pancake-developer/blob/master/docs/pages/contracts/v3/pancakev3pool.md. Pool `flash(address recipient,uint256 amount0,uint256 amount1,bytes data)` with `pancakeV3FlashCallback`. Requires chain/pool/factory verification and fee. Do not assume its BNB Chain liquidity automatically applies to Solana/Sui.
## DODO V2 DVM/DPP
Official https://docs.dodoex.io/en/developer/contracts/dodo-v1-v2/guides/flash-loan. Pool `flashLoan` sends base/quote, DVMFlashLoanCall or DPPFlashLoanCall callback depending pool, enforces non-loss conditions. Fee and liquidity are pool-specific; two kinds are not fungible.
## Instadapp Flashloan Aggregator
Official https://docs.instadapp.io/flashloan/contracts. `getBestRoutes(tokens,amounts)` resolver can quote fees/routes, `flashLoan(tokens,amounts,route,data,instaData)` runs through underlying liquidity. **Router not independent lender**. Store normalized `underlying_capital_resource_id` / correlation group to avoid double counting an Aave/Spark/Balancer pool and the same pool reached via aggregator. Needs receiver and gas; check chain-specific contracts.
## Fluid DEX V2 / Liquidity Layer
Official https://docs.fluid.instadapp.io/integrate/dex-v2-swaps.html documents flash accounting via DEX V2 `settle()` and callback. Flash accounting does not by itself establish a general-purpose flashloan balance/borrow ABI. Keep as swap/settlement research only until a specific liquidity-layer flashloan is source-qualified.

## Exclusions / weakly verified
Maker/Sky DSS Flash (synthetic mint) and Pancake V2 are research placeholders only until current official deployment/fee and contract proofs; not counted as verified independent cash lenders. Any ERC-3156 lender requires *specific implementation* (standard is not lender).
