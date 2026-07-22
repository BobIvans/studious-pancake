# PR-145 — Parallel PR merge coordination gate

This PR is an additive, review-only slice for coordinating the parallel roadmap
PR queue.

The uploaded second deep-audit roadmap does not define an explicit PR-145 item.
It defines PR-128 through PR-140, then says those blockers must be inserted into
the critical path before returning to the real-paper sequence PR-102 through
PR-105. In the current GitHub queue, later bridge/readiness PRs have also been
created while PR-140 and PR-138 are still moving in parallel.

This PR therefore adds a fail-closed queue coordination contract. It prevents an
operator report, release note, or readiness handoff from treating the queue as
settled while required PRs are still open, draft, stale, unmergeable, missing
green CI, missing evidence hashes, or closed without merge.

## What this slice adds

- `src/paper_queue_pr145.py`
  - `PR145RequiredPullRequest`
  - `PR145QueuePolicy`
  - `PR145QueueEvidence`
  - `evaluate_pr145_parallel_pr_queue(...)`
  - `assert_pr145_parallel_pr_queue(...)`

- `tests/test_pr145_parallel_pr_queue.py`
  - complete merged queue can be review-ready;
  - missing required PR fails closed;
  - open PRs fail readiness;
  - draft PRs fail readiness;
  - unmergeable open PRs fail readiness;
  - stale branches behind `main` fail readiness;
  - failed CI and unresolved review threads fail readiness;
  - paper/live claims remain blocked in this review gate;
  - closed-unmerged PRs fail readiness;
  - duplicate roadmap PRs and malformed hashes are rejected.

## Safety boundary

Passing this gate means only:

```text
parallel-pr-merge-coordination-review-ready
```

It still reports:

```text
paper_claim_allowed = false
live_claim_allowed = false
```

This is intentional. The gate is for review coordination, not for enabling paper,
live, signer, sender, RPC, Jito, Helius, MarginFi, Jupiter, or release publishing.

## Parallel PR compatibility

This PR intentionally does not mutate high-churn repository files:

- no `config/format_targets.txt` edit;
- no `scripts/verify_repo.py` edit;
- no workflow file edit;
- no Dockerfile or dependency lock edit;
- no existing simulator, planner, sender, runtime, data-lineage, readiness, or
  settlement module edit.

## Suggested verification

```bash
python -m pytest tests/test_pr145_parallel_pr_queue.py -q
python scripts/verify_repo.py --skip-dependency-audit
```

## Follow-up integration

A later integration slice can feed this boundary from real GitHub PR metadata,
required status checks, review-thread state, compare/ahead-behind data, and
release evidence artifacts. This first slice only creates the deterministic
offline contract and regression tests.
