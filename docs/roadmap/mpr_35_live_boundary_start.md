# MPR-35 start — Live boundary, target-host sandbox, archive and final promotion

This branch starts **MPR-35** from current `main` as an isolated review thread.

It is intentionally a start slice only. The full implementation remains to be built on top of this branch without enabling live trading.

## Target scope

MPR-35 owns the final default-off production boundary:

- target-host sandbox verification rather than management-only health checks;
- seccomp/AppArmor qualification under the real workload trace;
- digest-pinned production image and one signed dependency graph;
- live/signer/treasury/canary gates that remain unreachable by default;
- immutable release archive receipts over exact artifacts;
- final promotion only after signed bundle review, sender-free soak, DR rehearsal and explicit approval.

## Mandatory safety boundary

This start PR does **not**:

- enable live trading;
- enable signer IPC;
- enable private-key loading;
- enable transaction submission;
- claim paper-ready, shadow-qualified or production-ready state.

## Required follow-up implementation on this branch

The next code patch on top of this branch should introduce reviewable implementation for:

1. target-host sandbox inspection and deployment-state materialization;
2. immutable archive receipt verification for release evidence;
3. default-off live/signer/canary capability boundary;
4. final promotion preconditions that reject dev/pre-alpha artifacts.

## Parallel-work hygiene

- Created directly from `main`.
- Separate from MPR-CLOSE and earlier roadmap PRs.
- Safe to review independently before any deeper live-boundary implementation lands.
