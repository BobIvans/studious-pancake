# PR-047 operational rehearsal runbook

Use a dedicated canary account and the same deployment topology intended for
the staged release. Record timestamps, operator identity, environment, exact
candidate commit, commands or control-plane actions, observed result, recovery
time, and a sanitized evidence file. Never paste secrets, signed transaction
bytes or private-key material into evidence.

## 1. Restore drill

- take a supported backup using the PR-041 procedure;
- verify its checksum before restore;
- restore into an isolated target;
- run database integrity and audit-chain verification;
- prove that submitted/ambiguous attempts remain reconcile-only and are not
  automatically resubmitted;
- record recovery time and any manual intervention.

Pass only when restored state, fencing/idempotency state and immutable audit
history match the source evidence.

## 2. Restart drill

- stop the process during a pre-submission attempt and verify safe resume or
  reservation release;
- separately stop after submission may have occurred and verify
  `reconcile_no_resubmit` behavior;
- verify readiness stays false while recovery is unresolved;
- confirm no duplicate signature, bundle or capital reservation is created.

## 3. Key-rotation drill

- identify the current wallet/Jito credential owners using references only;
- rotate through the supported key-management process;
- revoke the old credential;
- prove the old credential no longer authenticates;
- prove the new reference is readable only by the intended runtime identity;
- run read-only readiness checks and keep live submission disabled.

A documentation-only review is `simulated=true` and cannot satisfy PR-047.

## 4. Kill-switch drill

- begin from an explicitly armed canary control state;
- trigger the manual kill switch;
- verify new permits/submissions are denied immediately;
- verify an outstanding ambiguous attempt remains under reconciliation rather
  than being silently cleared;
- verify operator status surfaces show the latched reason;
- clear the latch only through the documented human-controlled path.

## 5. Rollback drill

- trigger a configured canary rollback condition;
- move back to shadow without a code change;
- confirm sender/signing/submission paths are disabled;
- preserve the incident, attempt and reconciliation evidence;
- verify health may remain live while readiness is false;
- record the rollback duration and post-rollback monitoring result.

## Evidence record

Each manifest drill entry must set:

- one of `restore`, `restart`, `key-rotation`, `kill-switch`, `rollback`;
- `passed=true` only after observed acceptance criteria pass;
- `simulated=false` only for an actual rehearsal;
- timezone-aware `performed_at`;
- named operator and environment;
- SHA-256 pin to the sanitized evidence file.

Any failed or simulated required drill blocks production readiness.
