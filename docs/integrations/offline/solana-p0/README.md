# Solana P0 — offline technical dossier

**Prepared:** 2026-11-13  
**Purpose:** provide Codex with offline technical contracts for P0-1 indexed intake, P0-2 comparable Jupiter/0x quote capture, and P0-3 exact Raydium/Orca/Meteora state verification.

## Read order

1. `SOURCE_MANIFEST.json` — exact upstream locations, retrieval commits/blob IDs, version and mirror status.
2. `SOLANA_RPC_STATE.md` — RPC consistency, account reads, program/mint proof.
3. `JUPITER_SWAP_V2.md` and `JUPITER_SWAP_V2.openapi.yaml` — current official Jupiter API contract.
4. `ZEROX_SOLANA_SWAP.md` — current official 0x Solana request/response contract.
5. `DIRECT_STATE_RAYDIUM_ORCA_METEORA.md` — venue account state, math inputs, identity checks and license boundaries.
6. Task prompts in `docs/roadmap/p0-offline-execution-master-2026-11-13/tasks/`.

## Important truth about offline completeness

- Jupiter's complete OpenAPI 3.0.3 Swap API V2 specification is mirrored here as a raw official YAML snapshot.
- 0x, Solana RPC and venue references are captured here as technical extracts with exact canonical source URLs and retrieval metadata. The 0x public docs page is Open Beta and does not provide a stable checked-in OpenAPI file in this dossier.
- Raydium and Meteora upstream source paths/commits/blob IDs are pinned. This dossier records the program IDs, account families and decoding requirements; it does not vendor entire SDK repositories.
- Orca's current repository license is a custom Orca License (post-2025-02-27), not the former Apache-2.0 license. Do not copy its implementation or integrate its SDK until license use is approved. The public program/account facts are described here for independent review only.
- A source pin is not the same as a mirrored source file, a deployed bytecode attestation, or proof of live data. Consult the manifest status for each item.

## Agent rules

1. Read this dossier before changing P0 code. Never infer API fields or account layout from a ticker, UI, old adapter or HTTP 200.
2. Treat indexed APIs as discovery. Only chain account state, verified identities and venue-specific math can establish exact pool state.
3. Do not equate vault balance, TVL, indexed liquidity or one pool's total reserves with amount-specific executable depth.
4. All numbers remain integer/base-unit values until explicitly formatted for display. Resolve token decimals from verified mint accounts; handle Token-2022 extensions and transfer fees.
5. Keep quote and state captures replayable, timestamped, provenance-bound and secret-redacted.
6. No signer, sender, transaction submission, borrowing, account creation, or production promotion is in scope for these three tasks.

## Suggested local verification

From repository root:

```powershell
python docs/integrations/offline/solana-p0/verify_offline_bundle.py
```

The verifier is network-free. It checks the Jupiter OpenAPI snapshot against its upstream Git blob SHA-1 and checks required dossier files. It does not perform live provider qualification.
