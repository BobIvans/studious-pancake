# PR-132 — Observability store, migration, projection, export and replay integrity

PR-132 turns observability from a best-effort telemetry sink into a bounded
release-evidence surface. It is still offline and side-effect free: no provider,
RPC, sender, Jito, MarginFi, paper, or live path is enabled by this PR.

## Problems closed

The second deep audit identified three observability blockers:

1. A partial SQLite migration could insert version 17 while required tables were
   missing.
2. Projection rows used unconditional replacement, so lower-sequence replay or
   late events could regress `last_sequence_no` or terminal state.
3. JSONL export hard-coded `1970-01-01`, emitted payload only, and marked all
   pending outbox rows complete.

## Store invariants

`ObservabilityStore.migrate()` now:

- runs inside an explicit SQLite transaction;
- creates every current table with idempotent `IF NOT EXISTS` statements;
- runs a schema doctor before writing the migration row;
- stores a schema name and checksum with the migration version;
- refuses startup with `OBSERVABILITY_SCHEMA_INCOMPLETE` when an existing table
  is structurally incomplete.

`append()` now writes the event, outbox row, and projections in one explicit
transaction. Attempt and opportunity projections update only when the incoming
sequence is higher than the current projection. Terminal state is monotonic: a
later non-terminal event cannot clear a previously terminal projection.

## Export invariants

`export_jsonl()` now exports pending `work_type='export'` rows only. It writes
full event envelopes, not just payloads, to partitions based on the event's
actual UTC date and event type:

```text
date_utc=YYYY-MM-DD/event_type=<event_type>/events.jsonl
```

Each partition gets its own manifest row. Only the outbox IDs that were actually
included in the exported files are marked done.

## Replay invariants

Replay now produces a deterministic `decision_replay_hash` over the ordered
critical event timeline. With `verify=True`, it detects payload-digest drift and
terminal-state regression. This is still not full production decision replay;
that requires later planner/simulation/settlement pins, but PR-132 establishes a
stable integrity boundary for those future checks.

## Verification

Focused regression coverage lives in:

```text
tests/test_pr132_observability_integrity.py
```

Suggested local commands:

```bash
python -m pytest tests/test_pr132_observability_integrity.py -q
python -m black --check \
  src/observability/store.py \
  src/observability/export.py \
  src/observability/replay.py \
  tests/test_pr132_observability_integrity.py
python scripts/verify_repo.py --skip-dependency-audit
```

## Non-goals

PR-132 does not merge the observability database with the PR-121 lifecycle store,
does not enable paper/live trading, does not create release evidence from real
transactions, and does not claim finalized settlement. It only makes the current
observability surface fail closed when its schema, projections, export, or replay
integrity is insufficient.
