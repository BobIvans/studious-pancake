# Assignment — R-05 full exact atomic simulation

Copy/paste trigger: Implement R-05 using the current main ExactSimulationFinalizer, transaction compiler, atomic planner, financing repayment decoder, finalized economic ledger and Sui PTB contracts. Only simulate a route whose lender's R-02 capacity evidence and R-03 builder conformance are independently valid. Build a complete chain-local unsigned transaction/PTB containing the exact borrow, route instructions and repayment; verify it against current rooted account/object state and exact amount-specific quotes. No transaction signing, submission, borrowing or state mutation is allowed.

## Solana requirements
- Preserve exact instruction ordering and provider-specific brackets: Project 0 start/end; Kamino flash borrow/repay index; Jupiter borrow/payback requirements.
- Validate program IDs, account metas, writable/read-only privileges, mint/vault/token program identity, ATAs already existing when required, address lookup tables and message size.
- Compute-budget and priority-fee instructions must be finalized before index-sensitive repayment references are sealed.
- Bind blockhash/context slot, all affected accounts, route quote hashes, capital reservation, exact repayment decoder and message hash to the simulation report.
- Reject stale or non-independent RPC context, changed account state, unsupported Token-2022 hooks/extensions, insufficient compute/fee budget and any message mutation after simulation.

## Sui requirements
- Compile the PTB against a single current checkpoint and exact shared/owned object versions.
- Validate shared-object identities, linear coin/object use and complete flash receipt/hot-potato discharge in the same PTB.
- Confirm exact coinType, amount, fee, repayment coin and gas object budget. No legacy JSON-RPC fallback.

## EVM future lane
Do not represent offline Aave/Morpho/DODO/flash-mint semantics as a runnable executor. An EVM lane needs pinned chain ID/deployment/ABI, independently verified pool/token capacity, callback sender/initiator checks, receiver contract source/license/deployment evidence and fork/local-node simulation before it can enter R-05.

## Economic reconciliation
- Reconcile simulated token deltas with the exact financing obligation, fees, network cost and persistent account setup cost.
- Separate gross route output, lender repayment, network/gas costs, refundable rent and conservative net result.
- Never treat a successful simulation as a profitable or future-guaranteed trade. Preserve errors and negative receipts.

## Acceptance
- Positive and negative replay fixtures per supported lender/venue.
- Full unsigned transaction/PTB simulation with exact evidence and unchanged message binding.
- State-change, stale slot, wrong owner, missing dependency account, insufficient repayment, fee rounding, index shift, object-version conflict and compute/gas exhaustion cases.
- No signer/sender imports, no send call and no production authority changes.
