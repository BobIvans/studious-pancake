# MEGA8-03 — Solana strategy workers and statistically safe intelligence

Base at branch creation: `main@04480fa25d1117e9d20e7fe8caad23b16cd5ef4a`.

This package implements the **offline code contracts** for roadmap PR-186..PR-208
(NF-493..NF-584). It deliberately does not claim external protocol qualification,
production readiness, profitability, or live permission.

## Current-head reuse

MEGA8-03 extends rather than replaces existing owners:

- campaign / censoring / holdout truth: `src/production_qualification.py`;
- conflict workers, bounded multihop and shared split-flow:
  `src/strategy/conflict_scheduler.py`, `src/strategy/multihop_solver.py`,
  `src/economics/split_flow.py`;
- liquidation mechanics: `src/liquidation/`;
- non-atomic inventory separation: `src/inventory/`;
- advisory model and leakage boundaries: `src/decision/`;
- offline research effect boundary and promotion rules: `src/research/`;
- finalized economic accounting: `src/execution/economic_reconciliation/`.

The eight-pack says MEGA8-01 and MEGA8-02 are prerequisites, but also requires
dependencies to be proven by concrete current-head contracts rather than numbering.
This PR therefore records missing earlier-wave outcomes as operational/integration
blockers instead of inventing a successful dependency state.

## PR-186..194 — Solana worker contracts

The child modules under `src/mega8_03/` cover permission-aware keeper jobs,
CLMM/DLMM range residuals, opt-in RFQ/limit fills, post-execution scheduled-flow
research, Solana perp basis, a separate non-atomic spot/perp sandbox, liquidation
competition/cascade analysis, new-market activation/liquid-exit gates, and finalized
recovery attribution.

All planning outputs are unsigned and have no sender authority. ORDERFLOW-01
explicitly rejects unconsented or pre-execution harmful ordering. PERP-02 remains a
non-atomic research domain and cannot inherit an atomic flashloan permission.

## PR-195..208 — statistically safe intelligence

The research wave adds deterministic reference contracts for censored survival,
conformal uncertainty, causal hypotheses/transfer entropy, bounded event intensity,
graph and temporal baselines, active/meta learning, poisoning/drift quarantine,
evidence-bound explanations, support-aware OPE, safe simulation-budget exploration,
synthetic-vs-observed twin calibration, and competition/capacity decay.

These functions produce advisory statistics/models only. They cannot select trusted
programs, change permits, sign, submit, mutate remote state, or raise risk/capital
budgets.

## Provenance

No third-party source is copied or vendored in this PR. Upstream names in the
roadmap remain **REFERENCE candidates** for later independently pinned
license/conformance work. The implementation uses repository-internal contracts and
Python standard-library arithmetic so a missing upstream license cannot silently
become permission to copy.

## Operational truth

`config/mega8_03_coverage.json` is authoritative for this PR's scope status:

- 23 roadmap children;
- 92 NF identities, NF-493..NF-584;
- code status `IMPLEMENTED_OFFLINE`;
- operational status `BLOCKED_EXTERNAL_AND_UNQUALIFIED`;
- signing/submission/live/capital increase all false;
- no release or production-ready claim.

External/current deployment evidence, finalized multi-protocol campaign data and
model holdout/calibration campaigns are intentionally **not fabricated**.

## Rollback

Stop importing/admitting MEGA8-03 research outputs and remove its feature wiring.
No capital, signer, sender or release owner is replaced, so rollback does not require
key rotation or transaction recovery. Retain coverage/evidence history for audit.
