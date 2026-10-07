# Universal Quote / Build / Sign Contract

## Goal

A provider may quote and build, but never owns our private key.

```text
QuoteRequest
   ↓
parallel QuoteProvider[]
   ↓
NormalizedQuote[]
   ↓
correlation-aware ranking
   ↓
TransactionBuilder
   ↓
UnsignedExecutionPlan
   ↓
simulation
   ↓
LocalSigner (disabled in qualification)
   ↓
Sender (separate authority)
```

## QuoteProvider

Inputs:
- chain
- exact-in / exact-out
- full representation IDs
- amount
- wallet public address
- slippage ceiling
- allowed/blocked venues
- max account / byte / object constraints

Output:
- provider
- correlation_group
- in/out amounts
- provider/LP fees
- price impact
- route topology
- underlying venues/pools
- source timestamp/slot/checkpoint
- expiry
- raw evidence hash

## UnsignedExecutionPlan

Common:
- chain
- provider
- quote_ref
- representation IDs
- expected/min output
- provider fees
- network/priority/gas estimate
- flash-capital plan
- rent/gas sponsor plan
- route hash
- build hash
- signer requirements
- expiry
- simulation requirements

Solana:
- versioned/legacy
- instructions[]
- ALTs[]
- fee payer
- rent payer
- created token accounts[]
- close instructions[]
- serialized unsigned transaction optional
- byte estimate
- account lock count

Sui:
- Transaction/PTB bytes or composable Transaction
- input coin/object refs
- shared/owned object refs
- gas sponsor requirement
- checkpoint/object generation
- commands count

## LocalSigner

Private keys stay outside provider adapters.

Qualification:
`sign_enabled=false`

Production later:
- signer receives normalized plan + policy digest
- verifies provider/build hash
- verifies allowlisted programs/packages
- verifies max spend / min out / expiry
- verifies expected signer set
- signs locally

Never accept provider-returned instructions blindly into a live signer.

## Provider race

Do not simply send every candidate to every builder.

Suggested order:

### Solana
1. 0x
2. Titan
3. Jupiter reference
4. OpenOcean / OKX / Rango selected comparisons

For HOT candidates, race 0x + Titan + Jupiter concurrently within independent token buckets.

### Sui
Race Aftermath + Cetus + 7K/FlowX selected providers.
Use direct DeepBook/Cetus state for exact verification.

## Jupiter bottleneck

Jupiter Free general API is 1 RPS, but its submit/execute endpoints have separate higher Free buckets.
Therefore:
- quote/build must be diversified;
- landing does not need to be serialized behind the quote bucket.
