# Debt closure authority artifacts

This directory is reserved for reviewed MPR-NEXT-07 debt-closure evidence bundles.

No artifact in this directory should be treated as production-ready evidence unless it passes:

```bash
python scripts/verify_debt_closure_authority.py --evidence <path> --json
```

Synthetic, source-only, stale, non-replayable, or non-installed-runtime-bound evidence must remain blocked.
