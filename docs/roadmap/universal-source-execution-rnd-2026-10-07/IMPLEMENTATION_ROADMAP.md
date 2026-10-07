# Implementation Roadmap

## UXE-00 — Provider contracts

Implement generic:
- QuoteProvider
- TransactionBuilder
- UnsignedExecutionPlan
- ProviderCorrelation
- BuildEvidence

No signing.

## UXE-01 — Solana multi-provider quote/build race

Adapters:
1. 0x
2. Titan
3. Jupiter reference/fallback
4. OpenOcean comparator
5. OKX DEX
6. Rango

Token buckets are independent.

Retain all quotes, not only winner.

Integrate with existing GPR-02 VerificationQueue.

## UXE-02 — Sui multi-provider quote/PTB race

Adapters:
1. Aftermath
2. Cetus Aggregator
3. 7K/Bluefin7K
4. FlowX
5. OKX
6. Rango
7. direct DeepBook

No legacy JSON-RPC exact dependency.

## UXE-03 — Dynamic Universe

Implement live registry/pool ingestion + Generators A–G.

No 500 manual polling loops.

## UXE-04 — FlashCapitalGraph

Solana:
- P0
- Kamino

Sui:
- NAVI
- DeepBook
- Scallop

Read capacities/fees dynamically.

## UXE-05 — Slumlord rent financing

Implement only after UXE-01 instruction composition is stable.

Start with:
- one synthetic circular route
- existing settlement ATA
- one missing intermediate SPL ATA/account
- create -> use -> zero -> close -> repay

Then test multi-intermediate routes.

Token-2022 is a separate qualification gate.

## UXE-06 — CorrelationLedger

Compute residual/lead-lag features from retained evidence.

## UXE-07 — TON dynamic research lane

STON all-assets/all-pools -> Omniston -> swap.coffee -> direct venues -> chain truth.

No Solana-style atomic execution assumption.

## UXE-08 — Local signer interface, disabled

Implement signer contract and policy validation but keep:
`sign_enabled=false`

Production enablement is a separate approved phase.

## Parallelism

After UXE-00:
- UXE-01 Solana
- UXE-02 Sui
- UXE-03 universe/data

may proceed in parallel.

UXE-04 can proceed in parallel after shared identity contracts are stable.

UXE-05 depends on Solana instruction composition.

UXE-06 depends on normalized Observation V3.
