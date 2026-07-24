# MPR-NEXT-07 — Debt closure authority and archive diff sanity

## Purpose

This slice makes production-debt closure explicit and fail-closed.  It does not
promote the product to paper-ready, live-ready, or production-ready.  Instead it
adds a reviewed authority that can later consume real installed-runtime evidence
and decide which stable debt IDs may be considered resolved.

## Safety contract

A gate result can resolve mapped debt only when all of the following are true:

- the gate is mapped in `GATE_DEBT_MAP`;
- the evidence kind matches the gate;
- the claimed debt IDs are a subset of the stable gate mapping;
- the gate result is OK;
- the evidence is runtime-bound;
- the evidence is installed-artifact-bound;
- the evidence is fresh;
- the evidence is replayable;
- the run is CI-authoritative;
- the evidence is not source-only;
- the evidence is not synthetic;
- all required digests are lowercase SHA-256 values.

`MPR-31` is additionally blocked unless MPR-29 and MPR-30 evidence are present.

## Archive sanity

`scripts/archive_diff_sanity.py` compares two ZIP archives by path, size and
SHA-256 content hash.  With `--require-change`, identical uploads exit non-zero
so a byte-identical archive cannot be treated as production progress.

## Focused checks

```bash
python -m compileall -q src scripts tests
PYTHONPATH=. python -m pytest -q tests/test_mpr_next_07_debt_closure_authority.py
python scripts/production_debt_audit.py --json
```
