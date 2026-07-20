# PR-024 implementation bundle

This repository snapshot contains the implemented PR-024 quality gates and
runtime-defect repairs. It was prepared against the uploaded pre-PR-023
snapshot, so integrate PR-023 first and then apply `PR-024-ready.patch` or
cherry-pick the changed files.

## Merge order

1. Merge/apply PR-023.
2. Apply the PR-024 patch with `git apply --3way PR-024-ready.patch`.
3. Resolve only genuine overlap from PR-023; do not restore global `F821`
   suppression or imports of `src/legacy_arb_bot.py`.
4. Install dev requirements and run `python scripts/verify_repo.py`.

PR-024 intentionally does not implement packaging (PR-025), unified config
(PR-026), protocol conformance (PR-027/028), or the paper execution kernel
(PR-038).
