# MPR-15 — Rooted treasury and exactly-once accounting

## Purpose

MPR-15 replaces the caller-assembled PR-163 treasury model with one fail-closed,
sender-free authority for finalized wallet evidence, solvency, signed treasury
operations and replay-derived accounting. It covers production-readiness findings
F-337 through F-349 without enabling transaction signing, submission or live mode.

## Active authority

`src.treasury.rooted_accounting` is the canonical facade over four authority modules (`mpr15_common`, `mpr15_observation`, `mpr15_risk`, and `mpr15_ledger`). The historical
`src.treasury.financial_risk` import path is an explicit compatibility facade;
the unsafe implementation no longer exists beside the replacement.

## Rooted wallet evidence

Wallet admission is constructed only through `WalletObservationPackage.from_rpc_quorum`.
The boundary:

- retains bounded raw finalized RPC response JSON and verifies its SHA-256 digest;
- deterministically decodes native balance and every approved token account;
- requires identical request and decoded state across the quorum;
- verifies providers against a signed registry with independent operator and network-path groups;
- enforces collection-span, root-skew, future-time, age and root-lag limits;
- binds wallet, programs and token accounts to a signed chain registry and migration generation;
- rejects duplicate token accounts, missing account-state hashes and authority drift.

No constructor accepts a caller-supplied available balance.

## Treasury authorization

Funding and sweep requests are canonical hash-bound objects. An authorization is
created and verified through a trusted-key boundary and binds:

- exact request hash and scope;
- wallet-registry generation and policy hash;
- not-before and expiry times;
- one-time nonce and signer identity.

`DurableTreasuryLedger.consume_authorization` stores consumption under a SQLite
`BEGIN IMMEDIATE` transaction with uniqueness for both authorization and request.
A restart cannot make the authorization reusable.

## Exactly-once double-entry ledger

Every economic movement has a stable movement ID and a sequence of immutable
stage events. Each event requires balanced debit/credit postings and strict
per-kind topology/sign rules. The projection:

- rejects event-ID or idempotency-key reuse with a changed payload;
- permits only forward stage transitions;
- counts the latest eligible stage of one movement exactly once;
- derives UTC-day and rolling-window membership from the trusted occurrence time;
- counts consecutive outcomes by unique attempt identity;
- reconstructs risk state exclusively by replay and emits a hash-chained checkpoint.

The SQLite store uses WAL and `synchronous=FULL`; its public API is append-only.

## Reconciliation and latches

`DailyTreasuryReport.from_ledger` derives funding, withdrawals, PnL, fees, rent
and unresolved exposure from ledger movements rather than caller totals. A
chain-to-ledger variance beyond tolerance or unresolved exposure above the policy
threshold sets the hard latch and blocks capital reuse.

## Safety boundary

This package is deliberately offline and side-effect free. It does not contact
RPC providers, load private keys, sign Solana messages, submit transactions or
enable live trading. MPR-13/MPR-14 may consume its immutable identities after
their own authorities are merged; MPR-17 owns installed-artifact cutover and
operational qualification.
