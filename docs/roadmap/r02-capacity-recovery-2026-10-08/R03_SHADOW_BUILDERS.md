# R-03 = protocol-specific, SDK-conformant UNSIGNED builders — staged safely

## Entry policy
R03-00 contract-only coding and offline fixtures can start while R02 has structural/capacity blockers. However **NO live-capital-backed build, full-transaction qualification, signing or send** may be claimed until corresponding R02 provider's exact reserve/pool/fee state passes. Do not bypass R02 by treating SDK-built instructions as confirmed capacity.

## R03-00 Canonical contracts before provider adapters
Reuse already existing `UnsignedExecutionPlan`, `FinancingEvidence`, `FlashCapitalGraph`, `ExactSimulationFinalizer` and QPR authority/replay owner. Narrowly extend instead of duplicating. Standard result:
- `chain`, source/deployment/ABI pin, lender ID, underlying resource ID, canonical mint/coinType, exact atom amount, exact fee/repay projection, borrow and repay instruction references, instruction order / PTB hot potato, program owners/lock sets, expected account cost and native gas estimate (can be UNKNOWN but cannot be marked free).
- Correlation evidence for route comparisons; inputs all read-only/derived; output instructions or **unsigned** serialized Solana message / unsigned Sui PTB only.
- `build_status` separate from `capacity_status`: `BUILT_OFFLINE_UNQUALIFIED` is not `EXECUTION_READY`.

### R03-A Jupiter (Solana)
- Reuse `src/lending/jupiter_lend.py` and `src/lending/agg03_financing_ports.py`; official SDK helper `getFlashloanIx({connection,signer,asset,amount}) -> borrowIx/paybackIx`. `signer` may be an unsigned public pubkey only; never hold signing material.
- v0 message: compute budget -> borrow -> bounded route instructions -> payback (plus optional protocol-compliant ALT). Check borrow/payback account metas, admin PDA, program IDs, exact same mint/amount, last instruction semantics, original swap build identity; never silently create ATA.
- If SDK quote/cap state not pinned, record only offline verified fixture. A Jupiter admin fee=0 is not enough.

### R03-B Kamino (Solana)
- Pinned source `klend-sdk@13.0.2`, generated `flashBorrowReserveLiquidity.ts` / `flashRepayReserveLiquidity.ts` required; this offline kit vendors reserve state but NOT all builder transitive dependencies. Codex can use already installed pinned SDK source, or explicitly record missing generated instruction modules. Do not guess builder ABI.
- Repay must reference exact absolute borrow instruction index as `u8` in final message, after ComputeBudget and any other instructions. Validate index retargeting after route/build reorder and rejection if index beyond u8.
- Respect nonzero `ReserveFees.flashLoanFeeSf` / protocol rounding, token fees and fee receiver; no `Obligation` account needed in FLASH IX per reviewed klend source, but expected SPL destination ATA must preexist or emit `NEEDS_ACCOUNT_SETUP`.
- Build only; full message simulation is R05.

### R03-C NAVI (Sui)
- Use exact local vendor `navi/flashloan.ts.txt`, `navi/config.ts.txt`. SDK v1 vs v2 flash_loan_with_ctx selection based on *verified current* package config version; v2 adds `0x05` SuiSystemState, repay flash_repay_with_ctx uses clock `0x06`, storage, pool, receipt and coin.
- A PTB hot-potato receipt cannot be dropped, transferred improperly or repaid with wrong coinType. Validate exact amount/fee with integer units, object sharing/version and no coin leakage. Do not use `tx.sign`, `executeTransactionBlock` or SDK default legacy JSON-RPC transport.
- No synthetic successful on-chain checkpoint should be inferred from recorded Sui chain checkpoint alone.

### R03-D Project 0
- Conditional on preexisting marginfi account; reuse official @0dotxyz/p0-ts-sdk@>=2.8 references/previous marginfi conformance.
- `lending_account_start_flashloan` first after optional compute budget, and `lending_account_end_flashloan` last with repay accounting; P0 flash wrapper requires direct instructions, no CPI; cannot use generic Jupiter or Kamino interface for this.
- Never start one loan when existing position would be mutated unexpectedly or when true bank capacity unknown. If account not provided, only source-level fixtures.

## Test matrix
- Each builder handles wrong genesis/program/package, mint/coin type mismatches, stale cap/fee source, nonzero repay fees, missing ATA, mutable route reorder and duplicate borrow/repay with typed BLOCKED receipts.
- Byte-level source fixture equivalence to official SDK-generated unsigned instruction + account metas (may require Node SDK pin installed; if unavailable, cannot claim exact SDK conformance).
- No network needed for contract-only builder tests. No signer calls, no send, no account setup, no R03 promotion into live.
- Integration with `ExactSimulationFinalizer` planned R05: complete assembled message/unsigned PTB with real fee/cap proof, anti-stale state.
