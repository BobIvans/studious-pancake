# PR-142 — Paper/live readiness evidence gate

This PR adds a deterministic readiness gate for the roadmap sections that define
what counts as **Paper Ready** and **Live Canary Ready**.

## Scope

The current roadmap already defines the underlying proof families:

- transaction finalization;
- program execution proof;
- wallet lifecycle;
- evidence/observability;
- data lineage;
- live-only sandbox, Jito, settlement and drift evidence.

PR-142 turns those lists into a side-effect-free evaluator so reports cannot
claim paper or live readiness just because individual scaffold modules exist.

## What this patch adds

- `src/readiness_gate_pr142.py`
  - `ReadinessMode.PAPER` and `ReadinessMode.LIVE_CANARY`;
  - explicit required-gate lists for paper and live canary;
  - immutable `ReadinessEvidence` descriptors;
  - fail-closed checks for missing, stale, failed, unreviewed and placeholder
    evidence;
  - live-enabled evidence rejection before the gate is explicitly satisfied;
  - deterministic report hashing;
  - release-claim helper that prevents paper evidence from being labelled as
    live-ready.

- `tests/test_pr142_readiness_gate.py`
  - paper-ready positive fixture;
  - missing CPI proof blocks paper readiness;
  - placeholder hashes do not count as evidence;
  - unreviewed evidence blocks;
  - stale slot evidence blocks;
  - live canary requires both paper and live-only gates;
  - accidental live flag blocks readiness;
  - duplicate-gate latest evidence wins;
  - paper report cannot be relabelled as live-ready.

## Non-goals

- No live trading.
- No paper/live execution enablement.
- No signer, sender, RPC, Jito, Helius, MarginFi or Jupiter network call.
- No active runtime wiring.
- No claim that all upstream PRs are already complete.

## Why additive

Parallel PRs are moving `main`. This patch avoids shared hot files such as
`scripts/verify_repo.py`, `config/format_targets.txt`, workflow files and active
runtime modules. It provides the reviewable readiness contract that later release
tooling can wire into CI and operator reports.
