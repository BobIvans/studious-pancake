# PR-075 — Atomic vertical runtime stages

This patch wires the existing PR-058 sender-free atomic vertical into the
`PaperShadowRunner` stage contract without enabling live trading.

## Scope

`src.paper_shadow.atomic_runtime_stages.AtomicVerticalRuntimeStageSuite` exposes
five runner handlers:

1. `capital_sizing`
2. `planner`
3. `compiler`
4. `final_simulation`
5. `reconciliation`

The suite is deliberately not a discovery or candidate-construction engine. A
caller must provide an `AtomicVerticalCandidateAdapter` that returns a fully
formed `AtomicVerticalRuntimeInputs` bundle with:

- an `AtomicVerticalCandidate`;
- MarginFi provider pin hash;
- Jupiter contract pin hash;
- durable capital reservation id;
- account evidence hash;
- durable lifecycle trace id;
- optional provider pin map.

If any of those pins or lifecycle identifiers are missing, the suite fails
closed before a paper outcome can be recorded.

## Safety boundary

The suite never imports a sender, never signs, never submits, and never returns
truthy live-submission fields to the runner journal. It records only hashes,
provider pins, final fee/compute evidence, reconciliation status, and required
account identifiers.

This means the branch can be reviewed while earlier roadmap PRs are still being
applied in parallel. The actual production candidate adapter should land only
after the upstream PR-071..074 evidence is available on `main`.

## Verification

Focused tests:

```bash
python -m pytest tests/test_pr075_atomic_runtime_stages.py -q
python -m compileall -q src/paper_shadow tests/test_pr075_atomic_runtime_stages.py
```

Full repository check remains:

```bash
python scripts/verify_repo.py --skip-dependency-audit
```
