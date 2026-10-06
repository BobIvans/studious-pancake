# MASTER CONTEXT — RENEWED

## Current development state

The original pre-qualification package successfully produced the stacked QPR implementation wave:

- QPR-01 / PR #568 — canonical campaign/runtime/release authority;
- QPR-02 / PR #569 — governed provider/RPC qualification data plane;
- QPR-03 / PR #570 — campaign-start source intake and real-data handoff.

The top-level master handoff PR #567 is still open, so do not infer completion from public `main` alone.

The canonical continuation is **PR #571**.

## New strategy source of truth

PR #571 contains:

`docs/roadmap/gpr-parallel-radar-rnd-2026-10-06/`

Important files:
- `CODEX_START_HERE.md`
- `ASSET_REGISTRY_V2.json`
- `UNIVERSE_V2_EXPANSION.md`
- `INTERCHAIN_RELATIONS_V2.json`
- `ARCHITECTURE_CONTRACT.md`
- `IMPLEMENTATION_ROADMAP.md`

## New immediate goal

GPR-01 is no longer a placeholder-only candidate graph.

It is:

**Asset/Representation Registry + ResearchEconomicGraph + VerificationQueue**

The model must distinguish economic assets from executable representations.

Examples:
- Solana native USDC != Sui native USDC != Sui Wormhole USDC;
- Solana cbBTC != Solana Wormhole WBTC != Solana tBTC;
- Sui XBTC != Wormhole WBTC != Sui-Bridge WBTC != zwBTC;
- SOL on Solana != Wormhole SOL on Sui.

These can share an economic underlying without sharing an execution identity.

## Development order

```text
GPR-01 shared asset/representation + evidence-classified research graph contracts
        ↓
GPR-02 Solana radar/exact qualification
        ||
GPR-03 Sui shadow/exact-state qualification
        ↓
GPR-04 dynamic heat/watch scheduler
        ↓
GPR-05 structural transformation graph
        ↓
GPR-06 Solana<->Sui economic graph
        ↓
GPR-07 prefunded cross-chain simulator
        ↓
GPR-08 TON research lab
```

## Safety

Canonical mint/coin/Jetton identity is research input, not execution authority.

Keep signer, sender, transaction submission and live promotion unreachable.

## V2.1 refinement

PR #571 now carries 91 research identities, 14 first-campaign families, 9 DeepBook pool IDs, separate heat/execution/evidence axes, and a startup HARD_BOUND identity receipt. The broad universe remains cheap/dynamic until real evidence promotes relations.
