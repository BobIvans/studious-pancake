# MPR‑NEXT‑04 — Durable Economic Authority, DB cutover and Crash‑Recovery

> **Roadmap context:** This mega‑PR replaces fragmented SQLite stores with **one crash‑consistent durable economic authority** and removes unapproved direct database connects. It corresponds to the section labelled *MPR‑NEXT‑04* in the third‑pass production‑ready audit.  
> fileciteturn58file0L531-L576

This initial slice just opens the branch and adds fail‑closed verification scaffolds.

## New V‑scaffold verifiers added here

| Script | Focus |
|---|---|
| `scripts/verify_mpr_next_04_db_connect_linter.py` | Fails when active runtime modules import `sqlite3`/`aiosqlite` outside the approved authority factory. |
| `scripts/verify_mpr_next_04_atomic_transactions.py` | Fails when economic authority paths do not wrap attempt, reservation, fee and outbox mutations in **one** `BEGIN IMMEDIATE` transaction with CAS rowcount checks. |
| `scripts/verify_mpr_next_04_crash_recovery.py` | Fails when injected crash points leave double‑reserved capital or unreconciled terminal outcome. |

These verifiers currently raise `NotImplementedError` so the branch remains **fail‑closed** until real implementation lands.
