# Persistence Authority Cutover

Static snapshot: **137** direct `sqlite3/aiosqlite.connect`, **85** unapproved by current policy.

## Fast-start strategy
Do not wait for all 85.

### Stage A — campaign-only
Create one approved `CampaignEvidenceStore` owning:
- raw events;
- source cursors;
- gap/barrier history;
- quota leases or references;
- campaign manifest digest;
- replay heads;
- terminal campaign status.

No other campaign module opens SQLite directly.

### Stage B — production promotion
Migrate active groups atomically:
1. opportunity identity + admission;
2. capital/reservations;
3. provider quota/leases;
4. attempts/journal;
5. observability terminal truth;
6. signer/submission when ever enabled.

## Migration rule
A group migrates only with crash-injection tests proving no partial state after failure and deterministic restart reconciliation.

## Old PR
PR #443 has useful tests/contracts but is >1600 commits behind current main. Harvest, do not merge directly.
