# MASTER CONTEXT — R-01 complete / R-02 still blocked / R-03 unsigned

**Updated:** 2026-11-13  
**Repository:** https://github.com/BobIvans/studious-pancake  
**Current base at this documentation update:** \`main@28941ec5497cec2aad08ca9b6fcd10dfaeecb6aa\`. Always re-fetch latest main before implementation.

## Verified project sequence and PR history
- #579 restored the QPR/GPR/UXE owners to main without replaying the old large branches.
- #580 DIN-00 established credential admission and shared operator quotas.
- #581 DIN-02 added governed bounded Sui diagnostics and replay evidence.
- #582 DIN-01 added bounded Solana discovery and replay evidence.
- #584 completed R-01 reconciliation verification. **R-01 is closed; do not rerun or re-merge legacy integration branches.**
- #585 recorded partial real R-02 prerequisite observations and exact blockers. It did **not** qualify a capital provider.
- #586 is merged to main. It adds the R-02 offline SDK/source pack (19 pinned source files, layout facts, license/provenance and network-free verifiers) plus the R-03 unsigned builder handoff.
- #588/#589 are merged and provide the independent Solana P0 market-data handoff and pinned Raydium/Meteora references. These market-data tasks are not R-02 lender-capacity qualification.

## R-02 actual evidence and blockers
- Jupiter: FlashloanAdmin PDA was read at finalized slot 454401538; recorded owner and enabled/fee fields are in \`docs/verification/r02-2026-10-08/\`. It is not a TokenReserve/vault/effective flash-capacity snapshot.
- Kamino: executable program account observed at the same finalized slot. No full reserve, fee/capacity, market, vault or deployed bytecode attestation was established by that observation.
- NAVI: Sui chain checkpoint 331514367 was obtained; a subsequent GraphQL request timed out. No NAVI shared pool/config state was established.
- Project 0: no wallet-specific public authority/account was supplied. Wallet-free bank discovery is allowed; account eligibility remains separate and optional.
- R-02 output remains \`qualified_edges=[]\`; all 27 catalog candidates disabled. No accounts were created; no transaction was signed or sent.

## Offline technical knowledge now in main
- Broad 27-ID source ledger, protocol dossiers, provider economics/selection and machine-readable contract facts: \`docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/\`.
- R-02 focused SDK pins, Jupiter TokenReserve layout, Kamino prefix layout, NAVI SDK facts, P0 public discovery facts and inert vendor source files: \`docs/roadmap/r02-capacity-recovery-2026-10-08/offline/\`.
- R-02 authoritative task matrix/acceptance/R-03 builder constraints: \`docs/roadmap/r02-capacity-recovery-2026-10-08/\`.
- Market-data P0 offline contracts, Jupiter V2 OpenAPI, 0x request contract, Raydium/Meteora sources, and Orca license boundary: \`docs/integrations/offline/solana-p0/\`.

All dated source pins are historical, immutable provenance. Before implementing against an external SDK/API, verify whether an official newer version changes behavior. Add a new versioned pin/dossier; do not overwrite old evidence or infer deployed state from a source commit.

## Existing code owners to reuse
- QPR/DIN source admission, profiles, quotas, rooted RPC and replay: \`src/qualification_campaign/\`, \`src/provider_governance/\`, \`src/solana_parallel_radar/\`, \`src/gpr_sui_shadow/\`.
- Asset identity and market research: \`src/assets/resolution/\`, \`src/discovery/dynamic_universe/\`, \`src/research_economic_graph/\`, \`src/strategy/relation_generators/\`.
- Capital graph and amount economics: \`src/economics/flash_capital_graph/graph.py\`, \`src/economics/non_monotonic_sizing.py\`, \`src/economics/capital.py\`.
- Lender contracts: \`src/lending/jupiter_lend.py\`, \`src/lending/agg03_financing_ports.py\`, \`src/lending/kamino.py\`, \`src/lending/kamino_real_conformance.py\`, \`src/providers/marginfi/\`, \`src/lending/slumlord.py\`.
- Exact transaction simulation and paper lifecycle: \`src/execution/exact_simulation.py\`, \`src/paper_shadow/\`, \`src/runtime/core_v1_composition.py\`.

## Architectural boundary
Research universe stays broad: Solana, Sui, TON, EVM, LSTs, stables, wrappers, long-tail and cross-chain relationships remain researchable. FlashCapitalGraph is a separate resource/capacity dimension. An asset need not itself be flash-borrowable to be a route target; each route needs a supported settlement asset and one local atomic financing provider. TON/cross-chain signals remain separate asynchronous execution classes unless their own atomic settlement proof exists.

## Non-negotiable controls
\`sign_enabled=false\`, \`send_enabled=false\`, no keys/secrets in receipts, no new accounts/ATAs/obligations, no live borrow, no spend, no signer/sender enablement or production promotion. API list, docs fee, vault balance, TVL, off-chain NAVI response and historical snapshot are never positive capacity proof. Unknown remains UNKNOWN.
