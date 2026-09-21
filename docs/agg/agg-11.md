# AGG-11 — Independent EVM and Sui execution models

This package implements the code-side contracts for AGG-11 while keeping every
new non-Solana capability default-off. It deliberately does not reuse Solana
account-meta, slot, Solders transaction, signer, sender, or settlement types as
EVM/Sui authority.

## Work packages

- CHAIN-01 / NF-257..259 — chain/capability registry, exact chain-qualified
  amounts, EVM block/state identity, reorg detection, gas/nonce-bound operation
  plans and simulation binding.
- CHAIN-02 / NF-260..263 — exact Aave, Morpho, DODO and ERC-3156/GHO-style
  flash obligations. Callback sender, initiator, principal, fee and capacity are
  explicit evidence inputs rather than hard-coded deployment assumptions.
- CHAIN-03 / NF-264 — versioned Balancer v3, Uniswap v4 and Ekubo-EVM
  net-settlement domains. Liabilities cannot be netted across domains and every
  terminal asset delta must be zero.
- CHAIN-04 / NF-265..268 — Sui checkpoint/object-version/PTB model plus
  DeepBook, Cetus, NAVI, Scallop and Bucket obligation boundaries. Linear
  objects and hot-potato receipts must be consumed/discharged in one PTB.
- CHAIN-06 / NF-271 — evidence is qualified per chain, profile and deployment
  generation. Solana qualification remains owned by the existing Solana runtime.

## Operational truth

The packaged registry intentionally contains no executable deployment pins for
the new EVM/Sui capabilities. SIGN and SEND are absent from their allowed
effects; deployment/ABI/package/conformance blockers remain explicit. This is
the code-merge state required by the master plan when external operational
evidence is unavailable.

A future qualification campaign must pin one concrete network/deployment/fork
or Sui package/object fixture, prove state/math/simulation/economics/permissions,
prove the chain-specific gas/finality model, and only then update capability
status in a separately reviewed change.

## Invariants

1. Same address text on two chains is not the same identity.
2. EVM nonce replacement stays bound to one economic intent.
3. eth_call/simulation never becomes landing proof.
4. Aave simple/multi, Morpho, DODO base/quote and flash-mint capacity semantics
   remain distinct.
5. Net-settlement residuals must be zero in the same settlement domain.
6. Sui stale object versions, object double-consume, gas-object reuse and
   unclosed hot-potato receipts fail closed.
7. A qualification verdict for Base does not qualify Ethereum, Arbitrum, Sui or
   the existing Solana profile.
8. live_enabled remains false in AGG-11 code.

## Post-merge reconciliation

AGG-11 is merged through PR #508 /
`8d74566a70cde58366d04f46e6656022210aaf03`. Its package prerequisites
AGG-01 and AGG-04 are now merged as well, so missing aggregate receipts are not
current blockers. The historical default-off design remains unchanged.

EVM/Sui operational qualification is still absent: concrete chain/deployment,
ABI/package, fork/checkpoint, gas/finality and protocol conformance evidence must
be produced per exact chain/profile generation before any operational status can
advance.
