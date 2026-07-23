# NEW-MEGA-PR-01 — Canonical paper identity and legacy authority retirement

## Scope

This PR implements the first V7 audit package for the canonical paper root.
The V7 audit reports that the repository is still `NOT PRODUCTION READY`, and
specifically identifies deterministic canonical paper cycle identity, unsafe
schema certification and reachable legacy V3–V5 authorities as P0 findings.

## Implemented changes

- Separates immutable input identity from a unique durable run identity:
  - `input_identity` is still deterministic for source/config evidence;
  - `run_sequence` is allocated atomically in SQLite;
  - `cycle_id` now binds input identity, sequence and invocation time.
- Adds `paper_cycle_sequences` as a durable sequence authority.
- Makes canonical paper migration validate existing table contracts before
  `CREATE TABLE IF NOT EXISTS` can mark a database migrated.
- Adds SQLite `foreign_key_check` and `integrity_check` during startup.
- Keeps compatibility with previously persisted V1 report hashes when reading old
  reports, while new reports include `input_identity` and `run_sequence` in the
  hash payload.
- Adds a side-effect-free retirement gate for legacy V3–V5 authorities.

## Safety boundary

This PR does not enable live trading, signer access, sender access, Jito
submission, wallet loading, provider network calls or production-ready status.

## Verification

```bash
python -m py_compile \
  src/canonical_paper/model.py \
  src/canonical_paper/store.py \
  src/canonical_paper/platform.py \
  src/new_mega_pr_01_retirement_gate.py \
  tests/test_new_mega_pr_01_canonical_paper_retirement.py
python -m pytest -q tests/test_new_mega_pr_01_canonical_paper_retirement.py
```

## Follow-up still required

Full physical retirement of all legacy V3–V5 production surfaces should be
completed by wiring this gate into the release/cutover audit and by removing or
explicitly quarantining the retired modules from every production import graph.
