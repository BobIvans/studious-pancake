# MPR-TD-04 upgrade and rollback contract

This change establishes a sender-free release generation identity, a durable generation fence over an injected SQLite connection, a deterministic handoff state machine, and explicit rollback classification.

The contract does not fabricate accepted N-1/N artifacts. A real deployment drill still requires immutable wheel/image identities, a verified backup, measured capacity evidence, and operator authorization. Missing external artifacts remain promotion blockers.

## Required handoff order

1. Preflight immutable target identity and compatibility.
2. Stop admission and new claims.
3. Drain or quarantine in-flight work within a bounded deadline.
4. Checkpoint, verify, and back up durable state.
5. Run deterministic resumable migrations.
6. Activate the target generation and revoke stale workers.
7. Run postflight verification.
8. Resume admission only after all checks pass.

Rollback is allowed only when an immutable previous artifact and verified backup exist and the previous release can read current durable state. Destructive contraction requires forward recovery.
