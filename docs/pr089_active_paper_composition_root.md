# PR-089 — Active sender-free paper composition root

PR-089 connects the already-present discovery runner boundary with the
PR-075 atomic runtime stage suite while keeping live submission impossible.

## What this PR changes

`build_paper_shadow_runtime(config)` is now the supported composition root for
one paper/shadow cycle:

```text
runtime discovery
  -> detector candidates or verified empty market
  -> PaperShadowRunner
  -> CAPITAL_SIZING
  -> PLANNER
  -> COMPILER
  -> FINAL_SIMULATION
  -> RECONCILIATION
  -> durable paper outcome
```

The CLI now builds that runtime instead of constructing a bare
`PaperShadowRunner` without `stages=`.

## Dependency behavior

The current branch may still be missing the final verified PR-086/087/088
dependencies. PR-089 therefore distinguishes two states:

1. A real empty discovery cycle stays `healthy_idle`.
2. A real candidate with missing atomic dependencies becomes
   `blocked_pr089_atomic_dependencies_missing`.

That means a candidate no longer stops at `blocked_missing_stage_capital_sizing`.
The stage mapping is present, but the dependency gate fails closed until the
verified MarginFi provider, Jupiter V2 build path, exact fee workflow and atomic
stage suite are supplied.

## Active stage wiring

When a caller provides a complete `PaperShadowRuntimeDependencies` object,
PR-089 passes `AtomicVerticalRuntimeStageSuite.stage_handlers()` into
`PaperShadowRunner(stages=...)`.

The PR-075 suite already enforces exact message-hash identity between planner,
compiler, final simulation and reconciliation evidence. PR-089 does not weaken
that boundary.

## Safety boundary

This PR does not add or import:

- sender APIs;
- signing;
- RPC or Jito transaction submission;
- bundle polling;
- live mode;
- automatic resend.

Every stage output still passes the paper/shadow runner's forbidden-live-field
guard. The dependency gate returns `sender_imported=false` and
`live_mutation_allowed=false`.

## Suggested verification

```bash
python -m pytest tests/test_pr089_active_paper_composition_root.py -q
python -m pytest tests/test_pr075_atomic_runtime_stages.py \
  tests/test_pr076_paper_shadow_exit_semantics.py \
  tests/test_pr089_active_paper_composition_root.py -q
python -m compileall -q src/paper_shadow src/cli.py \
  tests/test_pr089_active_paper_composition_root.py
python scripts/verify_repo.py --skip-dependency-audit
```

## Remaining work

Full production paper/shadow completion still requires the real PR-086/087/088
artifacts and review evidence. Until those are supplied to
`PaperShadowRuntimeDependencies`, candidates are blocked rather than simulated as
paper successes.
