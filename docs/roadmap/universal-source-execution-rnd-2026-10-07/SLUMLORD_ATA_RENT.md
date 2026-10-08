# Slumlord ATA / Rent Financing R&D

## What Slumlord is

Source:
https://github.com/igneous-labs/slumlord

Mainnet program:
`s1umBj7CEUA6djs6V1c6o2Nym3QrqF4ryKDr1Nm1FKt`

Published repository verification hash:
`17d20483ee24bb0c1d0fead460f8eee7ccfc9bfcd9c811d295d3a56cc8e96065`

The program provides a zero-fee SOL flash loan intended for account rent.

Its README describes:
- Borrow transfers the available Slumlord balance minus one lamport to a destination.
- repayment must happen within the same transaction.
- CheckRepaid must follow Borrow as a top-level instruction.
- Repay can transfer the outstanding balance back.

## Important limitation

Slumlord does **not** make persistent ATAs free.

Rent financed by Slumlord must be recovered before transaction end so the SOL loan can be repaid.

Therefore it is attractive for circular arbitrage where intermediate token accounts:
1. do not exist before the transaction;
2. are needed only temporarily;
3. end with zero token balance;
4. can be closed before Slumlord repayment.

If the output token remains in a new ATA after the transaction, that ATA still needs persistent rent funding.

## Universal rent plan

Implement:

```text
AtaRentPlanMode:
  EXISTING_ACCOUNT
  PREFUNDED_PERSISTENT
  SLUMLORD_EPHEMERAL
  EXTERNAL_SPONSOR
  ROUTER_PAYER
  NOT_SUPPORTED
```

For each transaction builder, inspect every required token account.

### SLUMLORD_EPHEMERAL eligibility

Required:
- Solana only.
- Slumlord program/hash/runtime account verified.
- builder is instruction-composable.
- missing account can be created by our controlled signer/payer.
- account is guaranteed to be zero before close.
- close authority is ours.
- Token/Token-2022 account semantics are qualified.
- close recovers enough lamports to restore the Slumlord loan.
- byte/CU/account-lock budgets still fit.
- simulation proves repayment + CheckRepaid.

## Transaction sketch

```text
compute budget
Slumlord Borrow -> local rent-payer signer
create temporary token accounts / eligible ATAs
flash-capital borrow if applicable
swap leg 1
swap leg 2
...
repay trading flash capital
close zero-balance temporary token accounts -> rent-payer
Slumlord Repay
Slumlord CheckRepaid
```

Exact instruction ordering must follow every provider/lender constraint.

Project 0 is especially constrained:
- begin_flashloan near transaction start;
- end_flashloan must be last.
Therefore a P0 + Slumlord combination needs an explicit compatibility proof; do not assume both bookend rules can coexist.

## Builder compatibility

Best first targets:
- 0x: returns instructions and ALTs; reserves bytes for integrator instructions.
- Titan: SDK exposes route instructions and ready transaction; V3 supports a separate payer for SOL-denominated costs and that payer must co-sign.
- Jupiter instruction-builder paths.
- direct venue builders.

Harder:
- opaque/prebuilt-only transaction providers unless safely decompilable/rebuildable.

## Fee payer caveat

Solana validates the fee payer before program execution.
Slumlord cannot fund the network fee retroactively inside the same transaction.

Keep enough SOL for:
- network fee
- priority fee
- any required pre-execution fee-payer minimum

Slumlord's goal is **rent financing**, not zero-SOL transactions.

## Concurrency / contention

Treat the Slumlord account as a shared writable resource until proven otherwise.
Measure:
- current available balance
- account lock contention
- failed concurrent borrows
- landing latency
- capacity churn

Do not route every candidate through Slumlord automatically.

## Token-2022

Never assume standard SPL account sizing.
Use the correct token program and qualified extension/account-size semantics.
Fetch or derive the required rent-exempt amount for the actual account layout.

## Fallback

If Slumlord is unavailable:
- reuse existing persistent ATA;
- use a small local rent sponsor;
- use Titan V3 separate payer if compatible;
- skip route if net economics no longer pass.

## Acceptance

No claim of "all Solana pairs are rent-free".
The guarantee is:

> For an eligible atomic route whose Slumlord-funded temporary token accounts can all be closed and fully refunded before transaction end, the route may finance account rent without permanently consuming the trader's SOL principal.
