# PR-090 — Runtime truth documentation refresh

## Scope

This PR keeps the human-facing README aligned with the current capability matrix
after the latest paper/shadow, sender lifecycle, release evidence and limited
canary evidence gates landed.

The important correction is that paper mode is no longer documented as fully
`disabled`. It is available as a sender-free, fail-closed paper/shadow runner
boundary. That does not mean the repository is production-ready or live-capable.

This branch was rebuilt on the current `main` after parallel PR merges moved the
base branch during review.

## Updated truth model

- `flashloan-bot run --mode paper` can enter the durable paper/shadow runner.
- Missing upstream discovery/planner/compiler/simulation/reconciliation evidence
  remains `blocked`, not synthetic success.
- Degraded dependencies remain `degraded`, not healthy idle.
- Release-gate PRs are offline review/evidence contracts only.
- Live remains hard-denied and requires separate human-controlled canary work.

## Safety boundary

This PR does not change runtime behavior. It does not import a signer, sender,
wallet, RPC submitter, Jito submitter, retry loop, permit issuer or canary
controller. It only updates documentation and adds a regression test that checks
README claims against `config/capabilities.json`.

## Why this matters

The README is the first operator-facing safety contract. If it says paper is
`disabled` while the machine-readable matrix says paper is available, an operator
cannot tell whether the runner is missing or intentionally fail-closed. The new
wording separates these states:

```text
available but fail-closed != production-ready
release evidence gate != live trading enabled
manual canary review != automatic canary promotion
```

## Suggested verification

```bash
python -m pytest tests/test_pr090_readme_runtime_truth.py -q
python -m pytest tests/test_pr023_runtime_truth.py tests/test_pr090_readme_runtime_truth.py -q
python -m black --check tests/test_pr090_readme_runtime_truth.py
python scripts/verify_repo.py --skip-dependency-audit
```