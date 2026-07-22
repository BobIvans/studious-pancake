# PR-131 deterministic ATA/wSOL lifecycle and rent proof

This PR adds a sender-free, network-free lifecycle proof layer for account setup
and cleanup decisions required by the PR-131 roadmap.

## Scope

The new `src/account_lifecycle_pr131.py` module models:

- explicit Jupiter Build lifecycle request fields, so `payer`,
  `wrapAndUnwrapSol`, destination account, `maxAccounts`,
  `blockhashSlotsToExpiry`, Jito mode and swap mode are never hidden provider
  defaults;
- deterministic Associated Token Account PDA derivation for owner/mint/token
  program;
- existing-vs-create ATA policy with explicit idempotent create requirements;
- rent evidence and reservation checks using the account data size supplied by
  the policy;
- setup stage classification for pre-borrow own-capital, post-borrow
  flash-principal, route setup, swap and cleanup stages;
- wSOL funding, `SyncNative`, temporary-account and close-destination policy;
- cleanup checks preventing closure of pre-existing user accounts, rent refunds
  to unexpected accounts and authority mutation;
- two-leg deduplication checks for duplicate ATA creation or conflicting
  cleanup plans.

## Safety boundary

This patch does not:

- call Jupiter, RPC, Helius, Jito or MarginFi;
- sign or submit transactions;
- enable live or paper execution;
- create, close, wrap or unwrap any account;
- mutate the current planner.

It is an additive contract slice that later planner/compiler PRs can wire into
final transaction construction.

## Why this matters

The PR-131 roadmap notes that Jupiter setup instructions can create ATAs, wrap
SOL or reserve rent before flash principal is available. Those effects must be
reserved, staged and reconciled rather than treated as generic setup. The same
roadmap requires deterministic ATA/wSOL/rent behavior before paper readiness.

## Suggested checks

```bash
python -m pytest tests/test_pr131_account_lifecycle.py -q
python scripts/verify_repo.py --skip-dependency-audit
```
