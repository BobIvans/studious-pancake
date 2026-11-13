# Assignment — R-14 Solana RentSponsorPlanner integration

**Purpose:** make account/rent economics part of each Solana route choice without claiming that flash loans or provider sponsorship make ATAs free.

## Existing state to verify
- src/lending/slumlord.py already contains the sender-free Slumlord borrow, repay and CheckRepaid instruction constructors, reserve arithmetic and instruction-order validation.
- docs/roadmap/universal-source-execution-rnd-2026-10-07/RENT_SPONSOR_PLANNER.md documents a route-level planner and decision modes.
- Search of current main found the Slumlord adapter and the design document; do not assume a production RentSponsorPlanner class is already implemented. Confirm exact current code owners/callsites before coding.
- EXECUTION_BUILDER_CONTRACT.md describes sponsor/payer, fee payer and unsigned transaction fields. Verify every contract against actual provider docs and current code.

## Required decision modes
Implement or reuse this explicit classification:
- EXISTING_ACCOUNT — qualified pre-existing token account.
- PROVIDER_SPONSOR — provider-funded rent/fee payer with exact sponsor/co-signer semantics.
- SLUMLORD_EPHEMERAL — temporary account funding only if every Slumlord-funded account can be emptied and safely closed in the same transaction before Slumlord repayment.
- LOCAL_PERSISTENT — explicitly funded account that must remain non-empty/open at settlement.
- ROUTER_PAYER — provider payer that covers specified SOL-denominated costs, only when its exact co-sign/authority contract is proven.
- NOT_SUPPORTED — unknown/unsafe/non-composable setup.

## Decision order
1. Reuse an already verified account with correct owner, mint, token program, authority and lifecycle.
2. Evaluate a documented provider sponsor/payer (0x sponsor, Titan payer or later provider) only after current official docs, payer/co-sign/close-authority semantics and exact build output are pinned.
3. Consider Slumlord only for eligible ephemeral temporary accounts: borrow SOL, create/use temporary account as an unsigned instruction plan, empty it, close it with the correct close authority, repay Slumlord, then execute the protocol-required CheckRepaid sequence. Preserve the exact Borrow -> Repay -> CheckRepaid constraint already enforced by the adapter.
4. If final output must remain in a token account, use a persistent funding mode; Slumlord cannot be represented as financing a permanently non-empty ATA.
5. Reject a plan when any sponsor/close/repayment condition is unknown or all-in costs consume the conservative route edge.

## Economics to record per route
- number and kind of accounts; existing vs new;
- rent required, refundable amount, non-refundable amount and who controls close authority;
- sponsor charge, sponsor-funded rent and any refund/recovery conditions;
- network/base fee, priority fee, Jito tip only if separately enabled, compute units and instruction bytes;
- extra signer/co-signer and fee payer requirements;
- account locks and route composability;
- Slumlord loan principal, reserve constraints, repayment and CheckRepaid semantics;
- failure/landing cost and unknown fields.

UNKNOWN must never be encoded as zero or FREE. The planner is an economic feasibility component, not a wallet initializer.

## Work sequence
- Audit all current unsigned Solana builder and swap instruction owners, 0x and Titan sponsor documentation, Project 0/Kamino/Jupiter account requirements, Slumlord source pin and instruction tests.
- Freeze the RentSponsorPlan/evidence contract with R-03-00/R-13 owners before adapters integrate it.
- Implement deterministic offline decision tests using existing accounts, provider sponsorship, ephemeral Slumlord and persistent output accounts.
- Integrate only as metadata/unsigned instructions in the existing UnsignedExecutionPlan; no separate transaction composer.
- Connect to R-04 all-in route ranking after R-13/R-03 contract freeze.

## Mandatory negative tests
- final output account non-empty but marked Slumlord-funded;
- close authority mismatch or missing close instruction;
- Borrow/Repay/CheckRepaid reordered, missing or duplicated;
- sponsor payer requires unavailable co-signature;
- sponsor claims refundable rent but close conditions are not met;
- Token-2022 extension or token-program mismatch;
- rent/network/priority/compute cost unknown;
- Slumlord reserve/capacity stale or insufficient;
- shared route instructions break the lender's atomic bracket.

## Acceptance and safety
- Exact mode and cost receipt per proposed route, with source provenance and deterministic replay.
- Rejected routes carry typed reasons; no default to LOCAL_PERSISTENT with an invented budget.
- No ATA, token account, position or margin account is created on-chain. No signing, sending, borrowing, spending, deployment or production promotion. All generated instructions remain unsigned offline evidence.
- One review-only PR, source pins/licenses, exact tests, report and owner-reuse matrix.
