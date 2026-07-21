# PR-071 canonical execution domain

PR-071 creates a narrow ownership registry for execution-domain objects while
leaving live submission hard-denied. The goal is to prevent future runtime
composition from accidentally selecting a shadow, canary, or legacy sender DTO
as a production boundary.

## Production owners

The production execution-domain owners are:

- `src.execution.models.SimulationReport`
- `src.execution.economic_reconciliation.models.ReconciliationReport`
- `src.execution.canonical_domain.ExecutionReceipt`
- `src.submission.permit_bound.Sender`

These are recorded in `CANONICAL_EXECUTION_DOMAIN` and are resolved only when
the canonical-domain validation helper is called. The normal compiler import
path stays lightweight and does not import submission or economic reconciliation
modules at package import time.

## Quarantine boundary

The following compatibility symbols remain importable only for migration,
fixtures, or legacy status display:

- `src.execution.shadow.SimulationReport`
- `src.execution.shadow.ReconciliationResult`
- `src.live_canary.models.ReconciliationResult`
- `src.execution.live_control.LiveSubmissionPermit`
- `src.execution.live_control.PermitBoundSender`
- `src.execution.senders.rpc_sender.RpcTransactionSender`
- `src.execution.senders.jito_single_sender.JitoSingleTransactionSender`
- `src.execution.senders.jito_bundle_sender.JitoBundleSender`

They are listed in `QUARANTINED_EXECUTION_DOMAIN_SYMBOLS` and must not become
canonical production owners.

## Enforcement

`tests/execution/test_pr071_canonical_execution_domain.py` verifies that:

- each execution-domain role has exactly one production owner;
- legacy duplicate boundary classes are explicitly quarantined;
- `transaction_simulator.py` imports the canonical `SimulationReport` model;
- `canonical_sender.py` uses the permit-bound `Sender` protocol;
- `live_control.py` may retain `PermitBoundSender` only as a quarantined legacy
  adapter, not as a canonical sender protocol.

## Non-goals

This PR does not enable live submission, remove replay fixtures, or replace the
separate PR-069/PR-070/PR-073+ implementation work. It only adds the fail-closed
ownership map required before the broader execution-domain cutover.
