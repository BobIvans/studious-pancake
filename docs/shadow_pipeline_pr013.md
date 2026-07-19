# PR-013 shadow simulation pipeline

External Solana contracts were checked on 2026-07-19 against official Solana docs for `simulateTransaction`, common JSON structures, SPL token accounts, and Token-2022 transfer fees.

## Pipeline

`opportunity -> executable route -> economic plan -> pre-build PR-010 gate -> deterministic v0 compile -> fee/resource snapshot -> exact final-message simulateTransaction -> same-context reconciliation -> MarginFi repayment proof -> post-simulation PR-010 gate -> terminal shadow outcome`.

Shadow has no sender dependency. It never calls RPC/Jito/bundle submission and persists `executed=0`, `submitted=0`, `signature=NULL`, and `bundle_id=NULL`.

## Simulation contract

Final shadow simulation uses exact unsigned `VersionedTransaction` bytes encoded as base64 with `encoding=base64`, `sigVerify=false`, `replaceRecentBlockhash=false`, `innerInstructions=true`, commitment, and optional `minContextSlot`. `simulateTransaction` executes without broadcast. Replacement blockhash is not used for final decisions because it changes the exact message; an expired/stale context is a terminal reject/rebuild boundary for PR-014.

The primary evidence is one RPC response/context: `context.slot`, optional `apiVersion`, `err`, `logs`, `innerInstructions`, `unitsConsumed`, `fee`, `preBalances`, `postBalances`, `preTokenBalances`, `postTokenBalances`, and `loadedAddresses`. Requested `accounts` are only post-state cross-check data and never an atomic pre-state substitute.

## Hashes

`plan_hash` identifies the economic plan and excludes blockhash/signatures. `message_hash` is SHA-256 over exact message bytes and includes the blockhash. Shadow and future prepared-live paths must share both hashes for the same attempt; signatures are outside the equality claim.

## v0/ALT account mapping

Token `accountIndex` resolves against:

`static_account_keys + loadedAddresses.writable + loadedAddresses.readonly`.

The resolver checks ALT diagnostics ordering and lengths and rejects mismatches, out-of-range indexes, and native balance vector length mismatches.

## Token policy

SPL Token and Token-2022 are distinct program IDs. Token amounts use `uiTokenAmount.amount` as a base-unit integer string. `uiAmount` is ignored for money. Unknown programs, owner/mint gaps, malformed amounts, or missing monitored evidence fail closed. Token-2022 transfer-fee/withheld evidence is tracked conservatively; missing critical evidence blocks success.

## Accounting identity

Wallet PnL only includes declared wallet/strategy-owned monitored accounts. Protocol vault changes can prove repayment but are not wallet PnL. For native payer accounts, `observed_native_cash_delta = post_lamports - pre_lamports`; RPC fee, priority fee, and tip are decomposition/cross-check evidence and are not subtracted again because they are already embedded in payer lamport deltas. Rent locked and rent refunded are stored separately.

## MarginFi repayment proof

Program success is not enough. The shadow reconciler requires exact required repayment from verified terms plus deterministic simulation evidence such as repay logs/account deltas. Missing or ambiguous evidence results in `REPAYMENT_NOT_PROVEN`.

## Ledger semantics

The `ShadowPortfolioLedger` is hypothetical simulated state only. It mutates idempotently only when final simulation succeeds, reconciliation is complete, repayment is proven, and post-simulation feasibility passes. Actual wallet/resource snapshots are read-only for shadow accounting.

## Replay fixtures and redaction

Replay uses canonical request hashes to map exact simulation requests to sanitized official-shaped responses. It performs no DNS/network/RPC. Endpoint URLs and persisted provenance redact API keys/tokens.

## Terminal reason codes

`PRE_SIMULATION_FEASIBILITY_REJECTED`, `RPC_TRANSPORT_ERROR`, `RPC_RESPONSE_INVALID`, `SIMULATION_PROGRAM_ERROR`, `SIMULATION_SLOT_STALE`, `MESSAGE_HASH_MISMATCH`, `SIGNATURE_MODE_MISMATCH`, `ACCOUNT_KEYS_MISMATCH`, `BALANCE_VECTOR_LENGTH_MISMATCH`, `TOKEN_BALANCE_INVALID`, `TOKEN_PROGRAM_MISMATCH`, `OWNER_MISMATCH`, `INCOMPLETE_MONITORED_ACCOUNTS`, `REPAYMENT_NOT_PROVEN`, `FEE_MISMATCH`, `COMPUTE_LIMIT_EXCEEDED`, `RENT_CLASSIFICATION_UNKNOWN`, `SIMULATED_NET_PROFIT_BELOW_THRESHOLD`, `SHADOW_RECONCILED`.

## PR-014 boundary

PR-013 does not enable live mode and does not implement signing secrets, sendTransaction/sendBundle, durable submission journals, blockhash lifecycle, polling, resend/rebuild, landing confirmation, or on-chain reconciliation after landing.
