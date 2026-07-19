# PR-018 limited-live readiness gate

Verified on 2026-07-19 against the current public contracts for Solana RPC and Jito low-latency send. Solana `simulateTransaction` is used as non-broadcast evidence only and supports commitment, `replaceRecentBlockhash`, `sigVerify`, `minContextSlot`, and account-return options. Solana block height, blockhash validity, fee/rent, health, genesis and signature-status RPC methods remain dynamic point-in-time evidence. Jito bundle states are treated as `Pending`, `Landed`, `Failed`, `Invalid`, or ambiguous when status is null/timeout/unavailable; a transaction signature and `x-bundle-id` remain separate fields.

PR-018 is the first limited-live gate, not unrestricted live trading. The checked-in `config/live_risk.yaml` keeps `live_enabled: false`, so startup and normal operation remain shadow-only.

## Admission design

Limited live requires all of the following:

1. versioned non-secret risk config parses with no implicit caps;
2. deterministic SHA-256 over canonical redacted JSON;
3. `live_enabled: true` in that config;
4. fresh exact-hash operator arm record with a short expiry;
5. all `LiveReadinessService` gates return `PASS`;
6. final mutable gate recheck immediately before a `LiveSubmissionPermit`;
7. sender receives and durably consumes that single-use permit for the exact message hash.

A profitable quote, simulation success, signer reference, `--mode live`, or `LIVE_ENABLED=true` alone cannot submit. `PermitBoundSender` rejects `None`, stale, wrong-hash and used permits. Dry-run and readiness commands construct no signer, call no send method, and reserve no budget.

## Gates and latches

Readiness reports include every gate and evidence object: config schema, live flag, operator confirmation, safety latch, wallet reserve, allowlists, provider capabilities, RPC health, journal outstanding count, canary caps, exactly-one-tip policy and shadow evidence. `FAIL` or `UNKNOWN` denies.

Manual and automatic latches are stored durably in the live-control SQLite tables beside the PR-014 journal. Sticky reasons include simulation/live divergence, stale RPC or cluster mismatch, quota exhaustion, unhealthy provider/route, config drift, wallet reserve breach, daily/per-trade cap breach, ambiguous submission, unreconciled landed attempt, journal invariant violation, unexpected program/account and exactly-one-tip violation. Latches never auto-clear.

## Canary and accounting

Max outstanding live attempt is exactly one, derived from journal state. First live after arming must use the explicit canary policy in config; the code does not infer canary size from wallet balance. Money and caps are integer lamports/base units only. Actual loss/PnL is recorded only from landed and fully reconciled outcomes. Simulation/live divergence compares exact integer deltas in the same asset to the configured tolerance.

## Provider scope

Jupiter is the default execution provider only when its composable-instruction capability and allowlist evidence pass. OKX remains discovery in the checked-in config until explicitly promoted with verified capability evidence. OpenOcean and Odos are discovery-only and cannot enter a live compiler plan.

## External contract references

- Solana RPC `simulateTransaction`: https://solana.com/docs/rpc/http/simulatetransaction
- Solana `getBlockHeight` / `minContextSlot`: https://solana.com/docs/rpc/http/getblockheight
- Solana RPC index for `getSignatureStatuses`, `getLatestBlockhash`, `isBlockhashValid`, `getFeeForMessage`, `getMultipleAccounts`, `getHealth`, `getGenesisHash`: https://solana.com/docs/rpc
- Solana fees and rent: https://solana.com/docs/core/fees and https://solana.com/docs/rpc/http/getminimumbalanceforrentexemption
- Jito low latency transaction/bundle API: https://docs.jito.wtf/lowlatencytxnsend/
