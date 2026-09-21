# SUPER-07 — multichain, EVM/Sui strategy and non-atomic market closure

SUPER-07 aggregates W2-17, W2-18, W2-19 and W2-20. It is a closure over the
canonical owners already merged through AGG-11, AGG-12 and AGG-13, not a second
chain runtime or inventory engine.

## Canonical ownership

- DATA-05 / PR-129: `src.data_plane.external_datasets`
- CHAIN-01..04 and CHAIN-06 / PR-130..133,135: `src.multichain`
- CHAIN-05 and EVM/Sui strategy qualification / PR-134,136..139:
  `src.cross_chain.agg12`
- INV-01..05 / PR-140..144: `src.inventory`

`config/super07_coverage.json` records all 16 child aliases and all 56 primary
NF exactly once. `scripts/verify_super07_closure.py` rejects missing/duplicate NF,
missing owner/tests, invalid implementation dispositions, or any attempt to mark
the aggregate operationally qualified/live.

## Review debt closed here

Merged AGG-12 PR #502 had six unresolved automated review findings. SUPER-07
closes them without enabling new effects:

1. EVM cycle net is upper-bounded by first input → final guaranteed output minus
   explicit approval and flash-financing cost.
2. Euler-style JIT repayment cannot be below the requested borrow.
3. Sui cycle net is upper-bounded by final guaranteed output minus actual returned
   obligation and taker fee; borrow amount must match route input.
4. Every Sui shared route resource requires version/liquidity transition evidence.
5. Asset identity includes decimals, so raw units from different decimal domains
   cannot be treated as continuous.
6. Sui fee-rule activation state is part of the content-addressed decision digest.

## Operational boundary

This PR remains sender-free/default-off. A successful code closure does not claim:

- current external data entitlements or provider fleet qualification;
- deployed EVM/Sui/Starknet/Aptos protocol conformance;
- fork/loaded-state or PTB campaign completion;
- exchange trading connectors or actual-fill reconciliation;
- inventory margin/funding stress qualification;
- RWA custody/redemption/session rights;
- signer, sender, live trading or production readiness.

Those remain explicit blockers in the coverage artifact. Code merge,
qualification and activation are separate states.
