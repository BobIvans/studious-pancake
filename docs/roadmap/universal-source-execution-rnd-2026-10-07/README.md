# Universal Source + Execution R&D — 2026-10-07

Continuation after published GPR-01.

This package expands GPR-02 Solana, GPR-03 Sui and later TON work into one provider-agnostic architecture:

```text
many cheap data/radar sources
        ↓
Dynamic Asset / Market Universe
        ↓
ResearchEconomicGraph
        ↓
Relation Generators + CorrelationLedger
        ↓
bounded candidate queue
        ↓
parallel quote/build race
        ↓
exact chain-state verification
        ↓
FlashCapitalGraph + rent/gas plan
        ↓
unsigned execution plan
        ↓
simulation
        ↓
LOCAL signer only after a separate execution-authority gate
```

Goals:
- Jupiter 1 RPS must never be the only Solana quote/build lane.
- Sui must use multiple routers/builders, not one aggregator.
- TON remains a high-throughput research domain with its own asynchronous execution semantics.
- The broader market universe must grow from live registries/pools/books, not handwritten pair loops.
- Slumlord is modeled as Solana rent financing for eligible ephemeral token-account plans, not as a universal ATA replacement.
- No provider ever receives private keys.

This PR is R&D/source-of-truth only. It does not enable signer/sender/live capital.
