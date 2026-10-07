# FlashCapitalGraph

## Model

```text
FlashCapitalEdge
- chain
- provider
- asset representation
- available_amount
- fee_bps / fee model
- atomicity domain
- slot/checkpoint
- observed_at
- constraints
- required accounts/objects
- provider generation
```

The route solver should rank **net** economics after capital cost.

## Solana

### Project 0
- official SDK: `@0dotxyz/p0-ts-sdk >= 2.8.0`
- flashloan protocol fee currently 0
- discover banks dynamically
- direct transaction-level begin/end flashloan rules
- cannot be assumed composable with every other bookend primitive

### Kamino KLend
- discover live markets/reserves
- use flashBorrowReserveLiquidity / flashRepayReserveLiquidity
- read live reserve flash-loan fee/capacity/config
- do not hardcode supported assets

### Slumlord
Not trading capital.
Separate rent-financing edge:
`SOL_RENT_FLASH`.

## Sui

### NAVI
Use `getAllFlashLoanAssets()`:
- coinType
- max
- flashloanFee

Never hardcode the current number of supported assets or assume fee remains zero.

### DeepBook
Pool-local flash loans:
- borrow base/quote
- use in PTB
- repay with hot-potato receipt
- exact pool capacity/state required

### Scallop
Flash-loan fee documented at 0.1%.
Use when extra capacity/liquidity beats the fee.

## Solver

For candidate size X compare:

```text
gross route edge
- swap fees
- flash fee
- priority/gas
- rent/gas sponsor overhead
- expected failure cost
= expected net edge
```

Then run PR118/non-monotonic sizing over capital/provider combinations.
