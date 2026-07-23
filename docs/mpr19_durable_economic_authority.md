# MPR-19 durable economic authority checkpoint

This PR starts **MPR-19 — Crash-consistent durable economic authority and recovery** from the V9 mega-roadmap.

The roadmap assigns MPR-19 to the durable truth boundary: attempt identity, capital reservation, lease/fence semantics, append-only event journal, outbox delivery and recovery must be one atomic authority. This checkpoint is intentionally sender-free and offline. It does not enable live trading, signer IPC, private keys, Jito, Solana RPC, or transaction submission.

## What this checkpoint adds

- `src/durability/mpr19_economic_authority.py`
  - explicit `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK` writer transactions;
  - canonical versioned JSON identity that rejects bool, float, NaN, negative numeric identity fields and delimiter ambiguity;
  - atomic attempt creation with capital reservation, journal event and outbox event;
  - terminal transition with revision CAS and reservation CAS rowcount checks;
  - append-only hash-chain journal and materialized-state replay verification;
  - outbox FSM `QUEUED -> CLAIMED -> DELIVERED/DEAD_LETTER` with expiring claim token and stale-owner rejection;
  - private DB parent/file permissions and symlink fail-closed checks;
  - verified backup/restore activation hook.

- `tests/test_mpr19_economic_authority.py`
  - all-or-nothing rollback after each statement-level create step;
  - canonical identity negative probes;
  - revision CAS and reservation preservation;
  - stale outbox owner rejection after reclaim;
  - replay/materialized state tamper detection;
  - verified backup/restore rehearsal.

## Dependency boundary

MPR-19 depends on MPR-18 freezing the installed artifact/runtime interfaces. Until MPR-18 is merged and authoritative, this checkpoint remains a reviewable durable-authority foundation and must not be wired as the default production runtime.

## Safety boundary

This PR does not add or enable:

- signer access;
- wallet/private-key loading;
- transaction construction, signing, simulation execution or submission;
- provider/RPC/Jito/Helius/Jupiter/MarginFi/Kamino network calls;
- production/live/canary promotion.

## Follow-up work inside full MPR-19

This checkpoint does not claim full MPR-19 completion. Remaining work includes cutting older durable authorities over to the same schema/protocol, introducing renewable lease/deadline separation across runtime workers, expanding retention/archive acknowledgement into one generation-bound purge transaction and executing process-level race/crash matrices against the installed MPR-18 artifact.
