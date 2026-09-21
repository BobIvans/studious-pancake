# PR-357 — Adaptive Strategy Intelligence OS

Roadmap identity: **PR-357**. Actual GitHub PR number is assigned by GitHub.

Base audited at implementation start: `a96491af37594d0aacf2416aa74c56dbb1c9c304`
(merged PR-356 corrective completion).

## Mission

This PR installs one research-only, sender-free chain:

`strategy lifecycle/evidence decay -> new-market bootstrap -> PIT belief/world model -> decision-aware VOI`.

It intentionally does not create a second journal, point-in-time authority,
MarketPack authority, research frontier, allocator, signer, sender, release
authority, wallet owner, or capital authority.

Canonical reuse anchors:

- PR-356 `StrategyEvidenceCard` and research allocation contracts;
- existing MarketPack/mechanism-transfer/frontier owners;
- AGG-10 decision/VOI owner;
- PR-206 safe-bandit owner;
- PR-355 causal claim/evidence owners.

## Implemented scope

- 4 waves / 48 internal packages;
- 384 exact roadmap function identities with one machine-readable owner/disposition row each;
- 54 bespoke deterministic semantic primitives and 330 thin research-contract adapters;
- 40 immutable normative contract types;
- 80 preregistered hypotheses;
- 40 research challenges;
- 27 source/tool reference cards, all `REFERENCE_ONLY_REVERIFY`;
- zero new runtime dependencies.

### Wave 8

Append-only lifecycle states/transitions, multidimensional evidence age,
hard invalidators, deterministic survival/change-point/stopping primitives,
hysteresis, lineage inheritance, degradation attribution and read-only lifecycle
cards.

### Wave 9

Typed market bootstrap descriptors, prior applicability/freshness/rights guards,
negative-transfer fallback, source-schema collision/quarantine semantics,
equal-budget cold-start research contracts and MarketPack planning adapters.

### Wave 10

Point-in-time `BeliefState`, explicit source clocks, missingness and covariance,
uncertainty widening, deterministic joint scenarios, provenance receipts,
counterfactual downgrade and challenger/benchmark contracts.

### Wave 11

Decision problem IR, Bayes action/regret, EVPI/EVSI, deadline adjustment,
information redundancy/common-failure controls, sequential/adaptive sensing
contracts, value-of-computation, mandatory safety reservation and forced
abstention.

## Integrated offline vertical

`scripts/verify_pr357.py` exercises a deterministic fixture that:

1. invalidates stale deployment-generation evidence;
2. appends an `OBSERVING -> REQUALIFICATION_DUE` lifecycle receipt;
3. creates a pseudo-new held-out market descriptor;
4. keeps only eligible priors and records stale/rights-mismatched rejects;
5. compares equal-target-budget bootstrap policies;
6. builds a PIT belief with explicit missingness/covariance;
7. creates deterministic joint scenarios plus a falsifiable prior-transfer counterexample;
8. builds a decision problem and ranks information actions by deadline-adjusted EVSI net cost;
9. reserves mandatory safety information and proves missing safety forces `ABSTAIN`;
10. emits one deterministic integrated receipt with `execution_right=false`.

The fixture acceptance metric is held-out decision regret, not nominal PnL.

## Verification

Dedicated path-scoped CI runs:

- compile of all PR-357 code/verifiers/tests;
- PR-357 structural/semantic verifier;
- focused PR-357 tests;
- independent-process deterministic replay;
- PR-353/354/355/356 and Market Data Evolution regressions;
- repository canonical verifier;
- source import scan proving no signer/sender/wallet/release/capital effect owner is imported into PR-357 surfaces.

## External blockers and evidence honesty

The code/research integration scope is complete, but real held-out market
bootstrap, real lifecycle survival history, external foundation-model trials,
remote/live information acquisition, profitability and live finality remain
external/nonclaims. No external dependency was pinned merely because it appears
in the roadmap source ledger.

## Effect boundary

Always false:

- `production_ready`
- `live_enabled`
- `execution_right`
- `signer_access`
- `submission_access`
- `wallet_access`
- `remote_mutation`
- `automatic_promotion`
- `automatic_capital_increase`

MarginFi remains `PAUSED`. Slumlord remains `REQUIRED` for low-capital
qualification. Synthetic/paper/counterfactual outcomes are not realized PnL.

`MERGED != QUALIFIED != AUTHORIZED_LIVE`.

## Rollback

Revert this single PR. There are no stateful production migrations and no new
runtime dependency. Research records are additive/read-only; rollback does not
touch capital, signing, submission, wallet or release state.
