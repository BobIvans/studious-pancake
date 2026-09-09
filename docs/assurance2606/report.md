# MPR-2606 — test-strength assurance merge slice

## Scope

This branch is developer-only assurance tooling. It does not modify `src/**`, shared configuration, lock files, workflows, provider adapters, approval gates, signing, submission, live execution, or production readiness.

The slice is intentionally limited to measuring whether selected tests detect dangerous invariant-breaking mutations, producing minimal regression witnesses, and making mutation-runner outcomes fail closed. MPR-2606 does not become a second release authority or mutation-policy registry.

## Parallel-PR ownership check

Base is `main` at `68788d7f7f7da8a2e03b170f93c48af7421ee805`.

Current parallel chain observed before promotion:

- #473 / MPR-2602 — provider governance and sender-free vertical.
- #474 / MPR-2603 — human intervention and recovery authorization.
- #475 / MPR-2604 — production-closure/readiness truth and packaging.
- #476 / MPR-2605 — Jupiter protocol-qualification residuals; its PR body explicitly reserves #478 as the test-strength owner.
- #477 / MPR-2607 — shadow-soak evidence residuals.
- #479 / MPR-2608 — isolated signer/submission boundary; its PR body explicitly names #478 as mutation/test-strength assurance owner.
- #480 / MPR-2609 — limited-live canary authority.
- #481 / MPR-2610 — finalized economic ledger / realized-PnL boundary.
- #482 / MPR-2611 — production qualification / evidence authenticity.

No competing mutation runner or semantic owner of the `tools/mpr2606/**`, `tests/assurance2606/**`, or `docs/assurance2606/**` surface was observed in that chain. `ownership_clearance=clear_for_scoped_merge_at_observation` is therefore recorded as a snapshot, not a permanent claim; a newly appearing parallel mutation owner must trigger another ownership check before merge.

## Implemented

- `tools/mpr2606/pilot.py`: fail-closed, developer-only mutation pilot. It copies the checkout to an owned temporary directory, applies exactly one anchored mutation, runs a bounded selected pytest node set, writes JUnit-backed classifications, records SHA-256 before/after, and refuses source drift using exact source identity.
- `tools/mpr2606/pilot_mutants.json`: twelve source-pinned mutations T01-T12/R08-R09/D10-D11 from the supplied MPR-2606 seed, each with a concrete witness.
- `tests/assurance2606/test_safety_mutation_regressions.py`: minimal witnesses for simulation success, block-height/root-slot boundaries, durable candidate identity, generation immutability, retry boundaries, deadline expiry, and the matching-hash bool/int counterexample.
- `tests/assurance2606/test_runner_classification.py`: runner self-tests preventing zero-test, collection-error, skipped-only, timeout, or unexplained exits from being counted as mutation kills.
- `docs/assurance2606/scope-observations.json`: current anti-duplication ownership snapshot and scoped merge clearance.

## Result semantics

`KILLED_BY_ASSERTION` is emitted only when JUnit reports collected tests with assertion failures. Zero collected tests, collection/setup errors, all-skipped runs, timeouts, or unexplained exits remain non-kill outcomes. A green mutant is `SURVIVED_SELECTED_TESTS`.

The pilot never mutates the requested checkout. Mutations are applied one-at-a-time to temporary copies. Source hashes are recorded before and after; a changed original checkout prevents `complete=true`.

The credential environment supplied to child pytest is stripped of explicitly known wallet/provider key variables used by this repository. This is defense in depth only; it is not represented as an OS-level network sandbox.

## Verification truth

The first PR head `ae99961c704a72889f3de77d7acd907706f866cb` completed both repository `CI` and `Release authority` workflows successfully. Repository CI included repository verification, wheel/console smoke, secret scanning, and non-root runtime-image smoke. Final-head GitHub CI remains the merge authority after this documentation-only ownership reconciliation.

The supplied task also records earlier local seed evidence in which selected existing tests detected 4/12 mutations and the enhanced selected set detected 12/12, with 22 and 39 selected baseline cases respectively. Those numbers remain historical source-provided pilot evidence; they are not relabelled as a repository-wide mutation score.

The repository pins `mutmut==3.3.1`, but this scoped PR does not claim a completed full `config/mutation_policy.json` campaign merely because normal CI is green. The full policy campaign, OS-level no-egress qualification, fuzz/soak, and independent release certification remain verification/release evidence work and cannot be fabricated by a developer-only merge slice.

## Merge-readiness contract

This PR is merge-ready as an isolated developer-only assurance slice when all of the following are true on its final head:

1. GitHub reports the PR mergeable and normal repository CI/release-authority checks pass.
2. The final diff remains limited to `tools/mpr2606/**`, `tests/assurance2606/**`, and `docs/assurance2606/**`.
3. No current parallel PR owns a competing mutation runner/test-strength authority.
4. No source/shared-policy/workflow/lock/provider/signer/live changes are present.
5. The PR description does not convert historical 4/12→12/12 seed evidence into a full-policy or production-readiness claim.

A green merge of this slice means the scoped mutation/test-strength corpus and fail-closed runner are accepted. It does **not** mean the flashloan product is production-ready, that every mutation-policy target has been executed, or that independent release certification has passed.

## Safety

No provider calls, wallet loading, private keys, signing, transaction submission, live enablement, trading, automatic approval, or auto-merge are introduced by MPR-2606.
