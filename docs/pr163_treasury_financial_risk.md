# PR-163 — Treasury, wallet solvency and durable financial-risk accounting

This PR adds the first safe additive boundary for the production-readiness item
**PR-163 — Treasury, wallet solvency and durable financial-risk accounting**.

It does not call RPC, sign transactions, submit transactions, enable live canary,
or mutate the existing trading/economics path. The patch defines the
machine-readable contracts that a future runtime-owned treasury observation
service and durable accounting store must satisfy before any live admission can
trust money as available.

## Added files

- `src/treasury/__init__.py`
- `src/treasury/financial_risk.py`
- `tests/test_pr163_treasury_financial_risk.py`

## Main contracts

### Wallet registry

`WalletRegistryEntry` declares the authoritative wallet inventory:

- cluster genesis;
- wallet pubkey;
- purpose;
- signer backend;
- owner/custodian;
- hot/warm/cold classification;
- approved programs;
- approved token accounts;
- protected reserve;
- maximum exposure;
- funding/sweep policy IDs;
- retirement state.

### Runtime-owned wallet observation

`WalletObservationPackage` rejects caller-supplied balances and requires:

- `BalanceSource.RUNTIME_FINALIZED_RPC_QUORUM`;
- at least two independent finalized RPC endpoint identities;
- context/root slot evidence;
- response hashes;
- policy hash;
- registered wallet and token-account ownership.

This closes the contract gap where a caller can provide arbitrary
`native_lamports` to downstream capital logic.

### Solvency calculation

`compute_solvency_report()` computes available funds as:

```text
finalized wallet assets
- protected treasury reserve
- active capital reservations
- pending submission maximum debit
- rent liabilities
- estimated failure charges
- provider/network fee buffer
- withdrawal/sweep holds
```

Unresolved/ambiguous attempts must be covered by the pending maximum debit.
Negative availability is represented as a deficit and fail-closes admission.

### Durable financial-risk accounting

The ledger model uses explicit integer base units and accounting stages:

- predicted;
- simulated;
- confirmed;
- finalized;
- reconciled;
- booked.

Only finalized/reconciled/booked entries are folded into restart-safe risk
counters. Every counter is attached to an explicit window:

- UTC calendar day;
- rolling 24h;
- deployment window;
- canary window.

This prevents unbucketed `daily_realized_pnl_lamports` from being reset by a
process restart.

### Funding and sweep governance

`FundingSweepRequest` requires:

- allowlisted destination;
- exact simulated message hash;
- isolated signer requirement;
- non-revoked treasury authorization;
- request hash and policy hash binding;
- expiry checks.

The runtime contract never allows automatic withdrawal to a new address.

### Daily reconciliation

`DailyTreasuryReport` compares ledger-derived expected ending balance against
finalized chain balance. Variance above tolerance requires a hard latch.

## Acceptance coverage in this slice

| PR-163 acceptance | Coverage |
| --- | --- |
| No live admission uses caller-supplied unverified wallet balance | `WalletObservationPackage` and `reject_caller_supplied_wallet_balance()` fail-close caller-supplied balance |
| Risk counters survive restart/failover | `DurableRiskState` serializes windowed counters and ledger hash |
| UTC-day and rolling-24h limits are distinct | `RiskWindow.utc_day()` and `RiskWindow.rolling_24h()` |
| Ambiguous transaction reserves maximum possible debit | `SolvencyInputs` enforces unresolved reserve coverage |
| Finalized chain balances reconcile to internal ledger | `DailyTreasuryReport` |
| Wallet/token-account inventory drift blocks live | wallet/token account registry validation |
| No funding/withdrawal without treasury authorization | `FundingSweepRequest.validate()` |
| Multi-asset values never use binary float | all amounts are integer base units and asset mixing is rejected |
| Daily report balances exactly or activates latch | `hard_latch_required` / `assert_balanced()` |
| Restart cannot reset daily loss or consecutive-failure protection | durable window snapshots |

## Non-goals

This PR intentionally does not:

- fetch wallet balances from live RPC;
- add provider credentials;
- modify MarginFi/Jupiter routing;
- enable paper execution;
- enable live canary;
- implement a signer;
- implement remote treasury reports.

Future PR-163 integration can wire this boundary into the active wallet
observation service, lifecycle store, canary admission gate and finalized
settlement reconciliation path.
