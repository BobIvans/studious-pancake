# CODEX V2.2 DELTA — APPLY WITHOUT RESTARTING GPR-01

The user already sent the GPR-01 task to Codex. This file is an **additive delta**, not a new implementation wave.

Do not restart completed work and do not broaden scope beyond GPR-01.

## Apply these changes before the GPR-01 stop-report

1. Load the latest `ASSET_REGISTRY_V2.json` schema `gpr.asset-registry.v2.2`.
2. Add Sui `sSUI`:
   - coin type: `0x83556891f4a0f233ce7b05cfe7f957d4020492a34f5405b2cb9377d060bef4bf::spring_sui::SPRING_SUI`
   - economic asset: SUI
   - representation: LST
   - research-only until exact state qualification.
3. Use `FIRST_CAMPAIGN_FAMILIES_V2_2.json` instead of V2.1. Family count remains 14; F12 now includes sSUI.
4. Load `TRANSFORMATION_REGISTRY_V2_2.json`.
5. Do **not** create fake asset identities for:
   - USDT0 on Solana;
   - CCTP;
   - Wormhole route/mechanism.
6. USDT0 on Solana keeps native USDT mint `Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB`; USDT0 Legacy Mesh is transport/rebalancing topology.
7. CCTP connects native USDC representations and has no token mint of its own.
8. Wormhole is a bridge transformation; the wrapped target must use its representation-specific canonical identifier.
9. Preserve the existing safety rule:
   - transport edges = REBALANCE_ONLY / CROSS_CHAIN_SIGNAL as appropriate;
   - never insert them into the chain-local atomic graph.

## Existing GPR-01 goal is unchanged

Continue implementing:
- Asset/Representation Registry;
- evidence-classified ResearchEconomicGraph;
- HARD_BOUND identity receipts;
- VerificationQueue;
- deterministic fail-closed tests.

Then STOP as previously instructed.

If parts of GPR-01 were already implemented before this delta arrived, patch only the affected registry/relation/transport contracts and their tests. Do not rework unrelated code.
