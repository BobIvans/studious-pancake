# SUPER-02 — W2-03 + W2-04 dependency-order reconciliation

SUPER-02 closes the code-level integration debt created when AGG-03/AGG-04 were
merged before AGG-01. It does **not** turn merged code into operational
qualification and it keeps the lender profile default-off.

## Historical cause

The intended dependency chain for this slice is:

`AGG-01 -> AGG-02 -> AGG-03 -> AGG-04`.

Observed merge history instead placed AGG-03 (#495), AGG-02 (#496) and AGG-04
(#497) before AGG-01 (#501). The early PRs correctly stayed offline/unqualified,
but their artifacts retained blockers that became stale after the prerequisites
landed.

The important consequence for SUPER-02 is that the first implementation created
a second lender-neutral planner and stopped at
`CORE_V1_FINANCING_RAW_DECODER_NOT_COMPOSED`. That was the wrong closure
boundary: W2-03/W2-04 require reuse of the canonical planner/simulator/reconciler
owners.

## Canonical closure in this revision

This revision rebuilds SUPER-02 from current main and reuses the hardened
post-AGG debt work:

- `src/lending/agg03_financing_ports.py` bridges the pinned Jupiter Lend and
  Slumlord contracts into AGG-01 `FinancingPort`.
- `src/lending/financing_planner_adapter.py` adapts PRIMARY and auxiliary RENT
  financing into the existing canonical `AtomicMarginfiJupiterPlanner`; no
  second planner authority remains.
- Slumlord is an auxiliary RENT obligation. A Slumlord PRIMARY-lender path is
  not treated as a prerequisite for this package.
- `src/execution/agg03_financing_decoder.py` owns post-simulation lender
  repayment decoding and binds raw pre-state, writable-account coverage,
  lender reserve identity, exact message/simulation identity, attempt
  generation, and obligation digests.
- `src/paper_shadow/atomic_vertical.py`,
  `src/paper_shadow/exact_attempt_pr152.py`, and the economic reconciler carry
  lender-neutral repayment evidence without caller-supplied PnL.
- `src/runtime/core_v1_dependency_resolver.py` and
  `src/runtime/runtime_entrypoint.py` make the Jupiter Lend profile reachable
  from the installed paper command only through an explicit evidence manifest.
  Missing deployment/provider evidence stays BLOCKED.
- Existing lifecycle/capital owners are retained:
  `src/account_lifecycle_pr131.py`, canonical durable reservations, and the
  conflict-aware scheduler remain the authorities for ATA/wSOL/rent and shared
  resource constraints.

The former SUPER-02 files `src/lending/financing_adapters.py` and
`src/planning/atomic_financing_jupiter.py` are intentionally removed from the
PR diff by rebuilding from current main. Their useful behavior is represented
through the canonical owners above instead of parallel authorities.

## Child disposition

### W2-03

| Child | Current disposition |
| --- | --- |
| PR-081 | SATISFIED_BY_EXISTING — AGG-01 lender-neutral obligation contract |
| PR-087 | PARTIAL_EXTERNAL — capital/reservation owners exist; fresh wallet/reserve observations remain qualification input |
| PR-091 | CODE_CLOSED / EXTERNAL_QUALIFICATION_REQUIRED — Jupiter Lend port + rooted-state requirements |
| PR-092 | CODE_CLOSED / EXTERNAL_QUALIFICATION_REQUIRED — Slumlord RENT port preserves Borrow/Repay/CheckRepaid |
| PR-093 | PARTIAL_EXISTING / EXTERNAL_QUALIFICATION_REQUIRED — canonical PR-131 ATA/wSOL/rent proof and shared-resource scheduler exist; exact selected-profile evidence remains to be materialized |
| PR-119 | SATISFIED_BY_EXISTING / PARTIAL_EXTERNAL — challenger contracts remain default-off |

### W2-04

| Child | Current disposition |
| --- | --- |
| PR-090 | SATISFIED_BY_EXISTING — Jupiter V2 product contract |
| PR-094 | CODE_CLOSED_DEFAULT_OFF — lender-neutral financing now enters the canonical planner/runtime graph |
| PR-095 | SATISFIED_BY_EXISTING — instruction firewall remains canonical |
| PR-096 | PARTIAL_EXTERNAL — loaded-state/fork qualification is not fabricated |
| PR-097 | CODE_CLOSED / EXTERNAL_QUALIFICATION_REQUIRED — exact simulation and lender-aware reconciliation are composed |

## What is no longer a blocker

The following historical labels are retired in this revision:

- `AGG03_PREREQUISITE_EQUIVALENCE_UNPROVEN` — AGG-01/02 are now in main.
- `AGG03_GENERIC_FINANCING_SEAM_MISSING` — canonical FinancingPort adapter is
  physically composed.
- `CORE_V1_FINANCING_RAW_DECODER_NOT_COMPOSED` — a lender-aware exact
  post-simulation decoder exists and is wired.
- `CORE_V1_PRIMARY_FINANCING_ROLE_REQUIRED_FOR_SLUMLORD_PROFILE` — this was a
  misframed requirement for this scope; Slumlord is the RENT auxiliary
  obligation.

## Residual blockers

These remain real and must not be rewritten as PASS:

1. current Jupiter Lend deployment/admin/reserve evidence;
2. current Slumlord executable/PDA balance/state evidence;
3. evidence-manifest and repayment-decoder artifact qualification;
4. real provider draft source and governed RPC state capture;
5. exact selected-profile ATA/wSOL/rent lifecycle evidence;
6. AGG-04 requalification on the exact source/wheel/profile/deployment/config
   generation produced after this closure;
7. loaded-state/fork/finalized landing/soak evidence where required.

Therefore `implementation_status` remains PARTIAL and
`qualification_status` remains BLOCKED_EXTERNAL. Merge of this code is not a
production-ready claim.

## Safety

No private keys, signing, submission, wallet funding, remote mutation, live
activation or automatic capital scaling are added. The profile remains
sender-free/default-off.
