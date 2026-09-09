# MPR-2606 — test-strength assurance checkpoint

## Scope

This branch is developer-only assurance tooling. It does not modify `src/**`, shared configuration, lock files, workflows, provider adapters, approval gates, signing, submission, live execution, or production readiness.

The task is intentionally limited to measuring whether selected tests detect dangerous invariant-breaking mutations and to producing minimal regression witnesses. MPR-2606 does not become a second release authority or mutation policy registry.

## Observed coordination state

Base is `main` at `68788d7f7f7da8a2e03b170f93c48af7421ee805`.

- MPR-2602 is draft PR #473, current observed head `f9cb2632c376839042199fefcf9255f64364031d`.
- MPR-2603 is draft PR #474 and owns human intervention/recovery authorization.
- MPR-2604 is PR #475 and owns production closure/release integration.
- Branch `codex/mpr-2605-protocol-qualification` is observable but currently identical to main. Its future semantic scope is still reserved.

Therefore `ownership_clearance` remains `unresolved` until predecessor scopes are rechecked immediately before merge.

## Implemented in this checkpoint

- `tools/mpr2606/pilot.py`: fail-closed, developer-only mutation pilot. It copies the checkout to an owned temporary directory, applies exactly one anchored mutation, runs a bounded selected pytest node set, writes JUnit-backed classifications, records SHA-256 before/after, and refuses source drift using the exact Git blob identity observed on the accepted base.
- `tools/mpr2606/pilot_mutants.json`: twelve source-pinned mutations T01-T12/R08-R09/D10-D11 from the supplied MPR-2606 seed. The manifest names a concrete witness for every mutation.
- `tests/assurance2606/test_safety_mutation_regressions.py`: direct minimal witnesses for the selected gaps, including simulation success, block-height/root-slot boundaries, durable candidate identity, generation immutability, retry boundaries, deadline expiry, and the matching-hash bool/int counterexample.
- `tests/assurance2606/test_runner_classification.py`: self-tests that prevent zero-test, collection-error, skipped-only, timeout, or unexplained nonzero exits from being counted as mutation kills.
- `docs/assurance2606/scope-observations.json`: observed predecessor ownership and merge-clearance state.

## Result semantics

`KILLED_BY_ASSERTION` is only emitted when JUnit reports collected tests with assertion failures. Zero collected tests, collection/setup errors, all-skipped runs, timeouts, or unexplained exits remain non-kill outcomes. A green mutant is `SURVIVED_SELECTED_TESTS`.

The pilot never mutates the requested checkout. Mutations are applied one-at-a-time to temporary copies. Source hashes are recorded before and after; a changed original checkout prevents `complete=true`.

The credential environment supplied to child pytest is stripped of the explicitly known wallet/provider key variables used by this repository. This is defense in depth only; it is **not** an OS-level network sandbox.

## Seed evidence vs this PR

The supplied task records an earlier local seed pilot in which selected existing tests detected 4/12 mutations and the enhanced selected set detected 12/12, with 22 and 39 selected baseline cases respectively. Those numbers are preserved as source-provided historical evidence only; this PR does not re-label them as CI results or full-policy mutation scores.

This checkpoint has not executed the repository's pinned `mutmut==3.3.1` campaign, full locked CI, full repository suite, wheel/image qualification, fuzz, soak, external SDK/RPC probes, signing, sending, or canary activity. No `production_ready=true` claim is made.

## Remaining before MPR-2606 completion

1. Run baseline and this pilot in the accepted CPython 3.13 locked development environment and attach raw artifacts outside the checkout.
2. Run the existing `config/mutation_policy.json` scope with the repository-pinned mutmut version, including mandatory `unknown-code`, `ambiguous-retry`, and `expired-deadline` targets. Do not call the twelve-mutant supplemental execution-truth sample the full policy score.
3. Add bounded Hypothesis checks only where a real survivor/counterexample justifies them, preserving concrete replay examples.
4. Verify OS-level egress denial, unprivileged execution, resource bounds, no wallet/credential mounts, interruption cleanup, and stale-cache/hash rejection.
5. Recheck 2603/2605 semantics and path overlap immediately before merge. If another mutation runner owner exists, hand off this corpus rather than merging a second runner.
6. Submit any requested shared verifier/CI integration as a minimal handoff to the existing verification/release owner; do not modify shared policy/workflow from this branch.

## Safety

No provider calls, wallet loading, private keys, signing, transaction submission, live enablement, trading, automatic approval, or auto-merge are introduced by MPR-2606.
