# MEGA-PR-01 — Canonical Runtime, Durable State, Provider Plane and Production Sandbox

This is a **draft start slice** for MEGA-PR-01 from the deep production-readiness audit pack.

It opens the dedicated branch/review thread for making the product one installed sender-free runtime with one durable authority, writable/recoverable state, bounded provider/readiness pipelines, and an executable production sandbox under UID 10001.

## Scope anchor

MEGA-PR-01 should close the runtime/platform layer before protocol qualification or canary work:

- cut over `src.cli_pr189` into the real composition root
- remove legacy CLI/PM2/arb_bot production reachability
- consolidate lifecycle, paper, provider, reservation, result and outbox ownership
- add one SQLite migration/WAL/checkpoint/backup/retention policy
- move durable runtime paths under `/var/lib/flashloan-bot` in container mode
- load mounted typed secrets through secure single-open readers
- make seccomp/AppArmor/egress controls executable and tested
- bind `/ready` to task, DB, provider, queue, outbox and policy truth
- make metrics/logging bounded, durable and redacted

## Safety boundary

This branch must not:

- enable live trading
- enable private-key reads
- enable signer IPC
- enable transaction submission
- enable Jito submission
- claim paper-ready, live-ready, canary-ready or production-ready status

## Initial acceptance target

Follow-up commits should add implementation and tests proving:

- the installed wheel imports exactly one runtime root
- legacy entrypoints and retired stores are absent from the wheel/runtime graph
- UID 10001 can migrate, write, fsync, checkpoint, backup and restore inside the sandbox
- arbitrary egress is blocked
- double-reserve, duplicate-deliver and duplicate intent consumption fail closed
- readiness fails closed on worker death, stale evidence, read-only DB or excessive lag
