# AGG-12 — multichain arbitrage research and offline qualification

This slice implements the sender-free, default-off part of AGG-12 on the current
`main` while its aggregate prerequisites AGG-07 and AGG-11 are not yet merged.
It must not be interpreted as full AGG-12 completion or per-chain operational
qualification.

## Implemented scope

`src.cross_chain.agg12` provides deterministic contracts and admission functions
for all AGG-12 primary NF keys:

- NF-269 `starknet_aptos`: separate Cairo and Move dialect dossiers; EVM calldata
  reuse is rejected.
- NF-270 `emerging_chain_discovery`: source/access/simulation/gas/license/
  deployment evidence remains research-only when incomplete.
- NF-272 `strategy_evm_cycles`: 2-5 hop exact route continuity, shared state,
  funded gas, callback repayment and conservative net.
- NF-273..275: Compound/Sky/Morpho collateral-first mechanics with current terms,
  access, debt closure and non-cash reward exclusion.
- NF-276..283: basket, lending-aware, ERC-4626, directional-fee, netting, Pendle,
  flash-mint/PSM and LLAMMA invariants.
- NF-284..285: signed intent and opt-in orderflow admission; expired/unauthorized
  or harmful MEV paths fail closed.
- NF-286..287: Sui route/object continuity, repayment/gas constraints and joint
  fee/gas selection by conservative net rather than highest bid.

All financial values are integer-only. Evidence is content-addressed and every
`AdmissionDecision` hard-codes `live_enabled=False`.

## Deliberate blockers / prerequisites

The current `main` does not contain merged AGG-11 chain dialect execution
adapters or CHAIN-06 per-chain qualification, and AGG-07/RATE-02 is not merged.
Therefore this slice does not claim:

- executable EVM transaction building or fork qualification;
- executable Sui PTB compilation or shared-object mainnet evidence;
- deployed Starknet/Aptos adapter readiness;
- current production deployment pins for the named protocols;
- signer, sender, canary or live authorization.

Downstream integration must consume chain-specific evidence from the canonical
AGG-11 boundaries rather than adding a second executor here.

## Verification

Focused tests cover a positive fixture and fail-closed counterexample for every
strategy family, including shared-resource resets, capacity/debt leakage,
preview-vs-redeem mismatches, stale fee rules, invalid/expired intents,
non-consensual MEV, Sui object-version discontinuity and gas-bid dominance.
