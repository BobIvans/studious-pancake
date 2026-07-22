# PR-137 — Simulation CPI call graph and route provenance enforcement

This PR is an additive, review-only slice for the roadmap item **PR-137**.

It creates a fail-closed contract for proving what a simulated transaction
actually invoked. It does not call RPC, run live submission, sign transactions,
change Jito behavior, or wire into the active simulator yet.

## Roadmap requirement

The second deep audit requires PR-137 to prove actual programs/instructions
executed during simulation:

- preserve `innerInstructions`;
- preserve loaded addresses, return data, logs and account keys;
- reconstruct the full program call graph;
- compare planned route programs, top-level programs and observed CPI programs;
- reject unexpected CPI;
- bind route provenance to program IDs and deployment attestation, not labels;
- treat missing/truncated call-graph data as indeterminate and fail closed.

## What this slice adds

- `src/simulation_cpi_pr137.py`
  - `PR137RouteProgramIdentity`
  - `PR137InstructionObservation`
  - `PR137ExpectedRouteGraph`
  - `PR137SimulationCallGraphEvidence`
  - `evaluate_pr137_simulation_cpi_call_graph(...)`
  - `assert_pr137_simulation_cpi_call_graph(...)`

- `tests/test_pr137_simulation_cpi_call_graph.py`
  - complete call-graph evidence is review-ready;
  - top-level-only allowlist cannot pass without inner instructions;
  - unknown CPI programs are rejected;
  - route labels without program ID and deployment attestation are invalid;
  - missing planned route programs fail closed;
  - missing loaded addresses / return data / account keys or truncated logs fail
    closed;
  - call graph hash mismatch blocks permit evidence;
  - System transfers and Token-2022 transfer hooks require semantic checks.

## Safety boundary

Passing this gate means only:

```text
simulation-cpi-call-graph-review-ready
```

It still reports:

```text
execution_allowed = false
```

This PR intentionally does not mutate:

- `config/format_targets.txt`;
- `scripts/verify_repo.py`;
- workflow files;
- existing simulator/sender/planner modules;
- live or paper runtime behavior.

That keeps the patch low-conflict while parallel PRs continue moving `main`.

## Suggested verification

```bash
python -m pytest tests/test_pr137_simulation_cpi_call_graph.py -q
python scripts/verify_repo.py --skip-dependency-audit
```

## Follow-up integration

Later PR-137 integration work should wire this contract into the exact simulation
report/permit and then re-run the same call-graph comparison against finalized
`getTransaction` evidence in PR-138.
