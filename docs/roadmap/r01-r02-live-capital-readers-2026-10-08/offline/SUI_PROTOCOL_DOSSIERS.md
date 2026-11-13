# Sui flash-capital — pinned offline technical dossiers
Audited 2026-10-08. Reader network transport MUST be Sui gRPC and/or GraphQL via governed QPR/DIN-02 source paths; Sui Foundation mainnet JSON-RPC was disabled in July 2026 (official docs.sui.io/references/sui-sdks). Never reactivate retired JSON-RPC on timeout.

## NAVI — preferred high-level PTB flash API
Official https://sdk.naviprotocol.io/lending/flashloan
- **Use modular `@naviprotocol/lending`, NOT old `naviprotocol/navi-sdk`**: that repo explicitly calls itself Legacy. Docs expose `getAllFlashLoanAssets({env:'prod',cacheTime:30000})`; every asset has `max`, `flashloanFee`, `coinType`. `getFlashLoanAsset(coinType | assetId | poolObject)` and `getPool(coinType)`.
- Compose `flashloanPTB(tx,coinType,amount,{env:'prod'}) -> [balance,receipt]`; repay via `repayFlashLoanPTB` using receipt. Sui hot-potato receipt means PTB must account for full repay; no generic position-account initialization shown in flash helper.
- Supported/fee list is dynamic, may display several 0.00% assets but documentation explicitly says fees can apply; do not mark all as permanently free. `getAllFlashLoanAssets` off-chain SDK response is **discovery** until linked to live pool owner/package/checkpoint, precise CoinType and decimal metadata.
- Repo `src/economics/flash_capital_graph/graph.py` already implements `navi_sdk_snapshot` accepting **decimal strings** for max and flashloanFee. Coerce/serialize without Javascript floating-point loss, preserve `resource_id`, valid `flash_enabled`, `constraints`, `protocol_rounding_atoms`.
- Pinned historic Move interface in naviprotocol/protocol-interface@31d6401e298a10adb6b0e09c6137ab6d7024f08c only contains a small `flash_loan.move` structural contract; **not sufficient alone** to prove current deployed package ABI. Verify on-chain package/SDK if a live reader is attempted.

## DeepBook V3 — pool flash liquidity with shared book contention
Official https://docs.sui.io/onchain-finance/deepbook/deepbookv3-sdk/flash-loans
- SDK: `borrowBaseAsset(poolKey, borrowAmount)`, `returnBaseAsset({poolKey,borrowAmount,baseCoinInput,flashLoan})`; analogous `borrowQuoteAsset`/`returnQuoteAsset`. Borrow yields coin + non-discardable flash-loan 'hot potato'. Single PTB.
- No separate lender position initialization shown. Trading with limit orders may still require BalanceManager, which is **not** required by the flash primitive itself; route-level setup cost distinct.
- Source of capacity is *pool* and may contend with orderbook trading. Fee, caps and pool state require live object read; do not infer from SDK method shape or pool TVL. In example docs borrowAmount is JS number: avoid precision loss, adapt exact values before composing a PTB. Already has DeepBookCapitalProvider in FlashCapitalGraph.
- Sui official docs (CC BY 4.0); link is attribution to source, not proof of a live selected pool.

## Scallop — real official SDK v5, but FEES and default signer path
Official https://docs.scallop.io/protocol/fee: flash loans charged 0.1% at docs snapshot, plus Sui gas and potentially oracle fees. Upstream scallop-io/sui-scallop-sdk@ce59a37254c1851ae1d5e77b7d8ef690f0bdd28d, package.json `@scallop-io/sui-scallop-sdk@5.4.1`, Node >=22, @mysten/sui >=2.22.0, Apache-2.0.
- SDK supports read-only `Scallop({network:'mainnet',walletAddress:'...',...}).createScallopQuery()` and `query.getMarketPools()`. Wallet-scoped reads do not require private keys.
- **ScallopClient methods sign/execute by default**! For R02 use ScallopQuery ONLY; do not call client.flashLoan or builder.executor.signAndSendTxn. SDK provides `readTransport: 'graphql'` for certain reads and gRPC core transport; no old Sui JSON-RPC fallback.
- Need per-asset live flash cap, fee, supported flags and package ID independently read and confirmed; official doc fee 0.1% is not a specific on-chain snapshot.
- FlashCapitalGraph already has ScallopCapitalProvider; re-use adapter, do not create parallel graph.

## Cetus — pool-local flash / flash-swap research
NAVI official page compares Cetus as low-level Move flashloan. Without pinned current package/ABI/pool state and fee math, restrict to RESEARCH; do not claim it is account-free for *every* route. No positive graph edge from generic Cetus swap quote. Execution compatibility and hot-potato repayment are future R07.

## Bucket — USDB flash mint / loan, not general USDC flash capital
Official https://docs.bucketprotocol.io/developer-and-security/technical-resources documents dedicated Flash loan/mint mainnet module. Official USDB Peg https://docs.bucketprotocol.io/mechanism/usdb-peg documents PSM OUT 0.30% (as published) and flash-mint-arbitrage example. This is USDB-specific synthetic liquidity. Flash mint fee requires current module validation; old 0.05% claims are unverified at this audit. Do not conflate USDB mint capacity with USDC balance or 1:1 costless redemption.

## Suilend — discovery only
Official https://docs.suilend.fi/send/how-to-redeem-msend-and-claim-send-season-1 shows an app-level flashloan for redemption penalties. **Does not establish an independently documented general-purpose public flashloan SDK/ABI/capital pool.** Keep disabled research candidate until actual package verified.

## Risk rule
Sui gas object lifecycle / split+merge / PTB hot-potato repayment are part of route overhead. Even if no persistent lending position is needed, a successful PTB is not gas-free, and a failed PTB still consumes gas.
