# PR-180 — numeric, fee and spend ceilings

This PR starts the PR-180 production boundary by adding a reviewed numeric safety
registry and wiring the existing monetary domain objects into it.

## Scope in this slice

- Add `src/domain/numeric_safety_pr180.py` as the non-overridable hard ceiling
  registry for production numeric fields.
- Reject `bool` as an integer at the numeric trust boundary.
- Bound basis points to `0..10_000`.
- Bound token decimals before Decimal exponentiation.
- Bound compute-unit price and recompute priority fees against a hard ceiling.
- Preserve wide `u128` intermediate token math but require explicit
  `TokenAmount.to_wire_amount_u64()` narrowing before account/wire usage.
- Allow runtime config to lower ceilings through `SpendEnvelopeCeilings`, but fail
  closed if config attempts to raise beyond the signed/reviewed maxima.

## Safety boundary

This PR does not enable live trading, signing, sending, Jito submission, provider
promotion or canary activation. It only makes impossible numeric values fail
closed earlier in shared domain code.

## Covered defects

The snapshot reproduced that these values were accepted before PR-180:

```text
BasisPoints(1_000_000)
TokenMetadata(decimals=100_000)
ComputeUnitPrice(10**1000)
```

The new tests make those impossible, and also cover bool-as-int rejection,
explicit u128-to-u64 narrowing, priority-fee recomputation and config-lowering
semantics.

## Remaining PR-180 follow-up

Later PR-180 slices should wire the same registry into Jupiter request/response
validation, transaction compiler spend-envelope validation, signer-side exact
message debit recomputation, rent/ATA/setup SOL ceilings and release-policy
attestation.
