# MPR-33 — Crash-consistent durable economic authority and replay truth

This branch scaffolds the **MPR-33** workstream for `studious-pancake`.

## Scope anchor

MPR-33 turns the MPR19 durable layer into the single production authority for:

- attempts
- capital reservations
- event journal
- outbox
- replay integrity
- backup/restore
- crash recovery

## Initial intent

This README is a landing zone for follow-up commits that will add:

- canonical attempt identity and wallet-level capital invariants
- append-only journal reconstruction checks
- outbox FSM and signed delivery receipts
- crash/replay/restore acceptance tests
- migration and schema generation hardening

## Status

Draft scaffold only. Real implementation, tests, and cutover changes will follow in later commits on this same branch.
