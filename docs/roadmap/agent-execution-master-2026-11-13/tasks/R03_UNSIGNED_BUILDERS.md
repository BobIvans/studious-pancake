# Assignment — R-03 Protocol-specific unsigned builders

Copy/paste trigger: Implement only R-03 offline/unsigned builder contracts. Read the merged R03_SHADOW_BUILDERS.md and the local pinned SDK references first. Reuse FinancingEvidence, existing unsigned execution-plan/FinancingPort contracts, AtomicMarginfiJupiterPlanner, instruction firewall, Sui PTB ownership checks and current canonical transaction kernel. Freeze shared contracts before adding provider adapters. Produce deterministic unsigned instructions/PTB and byte-level conformance fixtures against the pinned official SDK. Report build conformance separately from live capital capacity: an offline builder is never an execution-ready route. Do not add or load a signer, use SDK sign/execute/send helpers, create accounts/ATAs/obligations, submit transactions or promote capital. Each provider is a separate small PR with source/commit/license pins, positive and negative fixtures, instruction order, exact mint/amount/fee/repayment semantics, account metas/owned/shared objects and replay.

## R03-00 — shared contract
- Canonical UnsignedExecutionPlan: chain/genesis, provider/deployment/ABI generation, resource ID, canonical asset ID, exact atom principal, fee numerator/denominator/rounding, required repayment, borrow/repay operation refs and order, lock/object dependencies, native fees/setup costs (UNKNOWN is allowed; zero is not).
- Separate build_status from capacity_status: BUILT_OFFLINE_UNQUALIFIED is never EXECUTION_READY.
- Bind every build to immutable FinancingEvidence, source pins, provider state fingerprint and exact route quote fingerprints. Fail on any generation mismatch.

## R03-A — Jupiter Lend (Solana)
- Reuse src/lending/jupiter_lend.py and src/lending/agg03_financing_ports.py.
- Source-pin the borrow/payback IDL and account metas. Verify same mint and exact amount, fee, destination/repayment accounts and protocol ordering.
- Build only an unsigned message/instruction pair. Missing ATA is NEEDS_ACCOUNT_SETUP, not permission to create it.

## R03-B — Kamino (Solana)
- Use the pinned generated flash-borrow and flash-repay SDK instructions; if required generated dependency files are absent, pin and add only lawful source references, otherwise report MISSING_PINNED_BUILDER_ABI.
- Repay must reference the exact absolute borrow instruction index as u8 after final ordering, compute-budget instructions and route insertion. Test index shifts/reorders/overflow.
- Respect dynamic fee/rounding and required fee receiver/token accounts. Do not create obligations for the flash path.

## R03-C — NAVI (Sui)
- Build v1/v2 PTB commands only according to verified current deployed package config. Check the exact flash_loan_with_ctx or flash_loan_with_ctx_v2 path, receipt type, required SuiSystemState/Clock/storage/pool objects, exact coin type, amount and fee.
- Discharge the hot-potato receipt in the same PTB with correct repayment coin and object versions; reject dropped/duplicated receipt or object conflicts.
- No tx.sign, executeTransactionBlock or legacy JSON-RPC client.

## R03-D — Project 0
- Conditional builder only when current official SDK/layout and pre-existing account are bound.
- Preserve P0's direct-instruction begin/end bracket semantics; validate direct instructions, exact bank/account/mint and start/end order. Never use deprecated mrgnlabs client as source of truth.
- Without supplied existing public account, keep only offline instruction fixtures.

## Exit
SDK byte-level equivalence or explicitly documented non-equivalence; deterministic replay; all negative cases; build/capacity status separated; no signer/sender or live route admission. R-02 must pass independently before a built plan can be attached to a live-capital candidate.
