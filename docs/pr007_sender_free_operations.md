# PR-007 sender-free operations

This runbook applies only to the installed paper/shadow artifact. Signers,
private keys, transaction submission, Jito send and unrestricted live mode are
outside this boundary and must remain unavailable.

## Startup and shutdown

Install the wheel into a clean environment, verify its digest, then start
`flashloan-bot shadow-soak run --duration 24h --json`. A missing credentialed
provider fails closed; CI may add `--fixture-mode`, but that output is never
promotion evidence. Stop through the service manager, retain the SQLite/WAL
pair, and verify the report before archive. Never edit cycle timestamps.

## Incident matrix

| Incident | Immediate action | Recovery evidence |
|---|---|---|
| Provider outage | Keep submission unavailable; readiness must block | freshness recovery and gap report |
| RPC disagreement | Quarantine observations until rooted quorum returns | slot/root comparison |
| Database failure | Stop intake, preserve DB/WAL, restore to a clean path | integrity check and hash-chain report |
| Secret compromise | Revoke provider secret and block readiness | revocation and replacement receipt |
| Config rollback | Reject an older generation unless authorized offline | old/new config digests |
| Release rollback | Stop, restore compatible state, install pinned prior wheel | wheel and schema digests |
| Unresolved reconciliation | Block readiness and retain reservation | terminal and reconciliation IDs |
| Signer isolation breach | Stop immediately and quarantine the environment | incident record; no automatic restart |

After restart, rolling update, migration or restore, run `flashloan-bot
shadow-soak report --from <state> --json`. Any duplicate sequence, broken hash
chain, fixture lineage, missing cycle, or insufficient measured duration is a
blocker. Backup during load must copy the database through SQLite's backup
mechanism rather than copying a live database file alone.

## Qualification

The independent verifier derives duration from the first and last stored
observation, requires unique hash-bound cycles, and rejects synthetic or
recorded lineage. The required real 72-hour soak, external artifact signatures,
image provenance and human review remain named blockers until their artifacts
exist. `PAPER_QUALIFIED` does not activate signer or submission capabilities.
