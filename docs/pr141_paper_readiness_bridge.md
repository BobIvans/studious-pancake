# PR-141 — Paper readiness dependency bridge

This PR is an additive, review-only bridge after the second deep-audit roadmap.

The uploaded roadmap explicitly defines PR-128...140 as new blockers that must be
inserted before the repository returns to the real-paper sequence:

```text
PR-128...140
THEN REAL PAPER
PR-102 type-safe real paper composition
PR-103 unified runtime truth
PR-104 actual security/chaos evidence
PR-105 actual >=72-hour shadow soak
```

The same roadmap also says PR-105 soak must measure:

- exact paper vertical;
- CPI call graph;
- observability;
- data lineage;
- no sender.

There was no explicit PR-141 item in the uploaded document. This patch therefore
creates a narrow bridge gate for the handoff from the new blocker queue back to
PR-102...105, without claiming any runtime capability.

## What this slice adds

- `src/paper_readiness_pr141.py`
  - `PR141RoadmapItem`
  - `PR141PaperSoakScope`
  - `PR141BridgeEvidence`
  - `evaluate_pr141_paper_readiness_bridge(...)`
  - `assert_pr141_paper_readiness_bridge(...)`

- `tests/test_pr141_paper_readiness_bridge.py`
  - complete bridge evidence is review-ready;
  - missing PR-128...140 dependencies block the bridge;
  - incomplete dependencies block the bridge;
  - merged dependencies require an evidence hash;
  - wrong critical-path group blocks the bridge;
  - unresolved blockers fail closed;
  - PR-105 soak scope must include exact paper vertical, CPI call graph,
    observability, data lineage and no sender;
  - live-after-soak PRs cannot start before PR-105 is complete.

## Safety boundary

Passing this gate means only:

```text
paper-readiness-bridge-review-ready
```

It does not enable live, sender, signer, RPC, Jito, MarginFi, Jupiter, paper
execution, runtime promotion, or release behavior.

The result intentionally reports:

```text
live_canary_allowed = false
```

## Parallel PR compatibility

This patch is intentionally low-conflict and additive. It does not mutate:

- `config/format_targets.txt`;
- `scripts/verify_repo.py`;
- workflow files;
- existing simulator/planner/sender modules;
- Dockerfile or dependency locks.

## Suggested verification

```bash
python -m pytest tests/test_pr141_paper_readiness_bridge.py -q
python scripts/verify_repo.py --skip-dependency-audit
```

## Follow-up integration

Later work can connect this bridge to real repository PR metadata, release
evidence artifacts, PR-102 composition acceptance, PR-105 soak reports and the
live-canary gate. This first slice only makes the dependency boundary explicit
and testable.
