# PR-102 — Type-safe real paper composition boundary

PR-102 hardens the PR-089 sender-free paper/shadow composition root. The goal is
to prevent arbitrary non-`None` objects from unlocking the active atomic paper
vertical before PR-099, PR-100, and PR-101 have produced the reviewed runtime,
package, and MarginFi/Jupiter evidence that the roadmap requires.

## What changed

- `PaperShadowRuntimeDependencies` no longer accepts broad `Any` sentinels.
- The composition seam now names explicit dependency contracts:
  - `ExactFeeCapitalWorkflowDependency`;
  - `VerifiedMarginfiProviderDependency`;
  - `JupiterV2BuildDependency`;
  - `AtomicVerticalRuntimeStageSuite`.
- A complete dependency set must satisfy runtime validation before
  `AtomicVerticalRuntimeStageSuite.stage_handlers()` can be wired into the
  runner.
- Plain `object()` values, evidence-disabled MarginFi providers, and execution-
  disabled Jupiter build clients fail closed with
  `blocked_pr102_type_safe_dependency_rejected`.

## Safety boundary

This PR does not create real PR-099/100/101 evidence, does not build MarginFi
transactions, and does not import a sender. It only makes the current paper
composition root refuse fake dependency identities.

Live submission remains unreachable:

- no signer;
- no RPC submitter;
- no Jito submitter;
- no wallet mutation;
- no resend path;
- no canary or live enablement.

## Expected state after merge

A default candidate with missing dependencies still blocks with the PR-089
missing dependency reason. A candidate with fake non-`None` dependency objects
now blocks with the PR-102 type-safety reason. Only reviewed, evidence-carrying
dependencies may unlock the existing sender-free stage suite.
