# SUPER-06 — research evidence, model governance and frontier benchmarks

SUPER-06 closes **W2-16 + W2-21** over canonical code that is already merged.
It intentionally does not create another ML runtime, research evidence store,
promotion authority, signer, sender, or treasury owner.

## Reused implementation

- W2-16 / PR-123, PR-124, PR-125: merged AGG-10 (#500),
  `src/decision/agg10.py` and `tests/test_agg10_intelligence.py`.
- W2-16 / PR-145, PR-149 and W2-21 / PR-146, PR-147:
  merged AGG-14 (#509), `src/research/*` and
  `tests/test_agg14_research_system.py`.
- W2-21's OPS dependency is present through merged AGG-09 (#505); solver/runtime
  prerequisites are present through merged AGG-05 (#498).

The closure manifest contains exactly seven child scopes and 34 primary NF:
NF-216..238, NF-308..317 and NF-323. Adjacent AGG-14 PRODUCT-01 NF-318..322 are
explicitly excluded from SUPER-06 so product work cannot inflate this package's
completion.

## What this PR adds

- one machine-readable SUPER-06 child/NF/evidence map;
- one fail-closed verifier that cross-checks AGG-10 and AGG-14 coverage;
- regressions for scope inflation and unsafe promotion flags;
- explicit operational blockers carried forward instead of turning
  IMPLEMENTED_OFFLINE into production or live readiness.

## Operational truth

Implementation closure is verified from merged code, tests and coverage
artifacts, but operational status remains **UNQUALIFIED / DEFAULT_OFF**.

The important residual evidence includes actual LIVE-03 sent-attempt labels for
NF-223, qualified defensive-tool evidence, QUBO/quantum/accelerator experiments,
a concrete federated-learning use case with participant consent, and a pinned ZK
statement/proof system. A positive research benchmark still reaches only the
existing reviewed integration/qualification path; it never grants execution
authority.

## Verification

```bash
python -m compileall -q scripts/verify_super06_research_frontier.py tests/test_super06_research_frontier_closure.py
python scripts/verify_super06_research_frontier.py --json
python -m pytest tests/test_super06_research_frontier_closure.py tests/test_agg10_intelligence.py tests/test_agg14_research_system.py -q
```

Repository CI and Release authority remain authoritative for merge.
