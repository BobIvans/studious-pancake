# MEGA-PR-03 — Isolated live execution, finalized reconciliation and bounded canary

## Status

This branch starts **MEGA-PR-03** as one long-lived GitHub PR with reviewable
checkpoint commits. The first checkpoint is:

```text
CP1 — canonical live-boundary convergence
```

CP1 does not enable signing or submission. It converges the existing PR-199,
PR-202, PR-211, MPR-14, MPR-16 and MPR-17 safety surfaces under one explicit
ownership and dependency contract.

## Roadmap boundary

MEGA-PR-03 absorbs the former PR-08, PR-09 and PR-10 responsibilities:

- isolated signer and bounded RPC/Jito submission;
- finalized settlement and unknown-outcome recovery;
- signed bounded canary, persistent loss latches and independent approval.

The roadmap permits only **bounded live-canary-ready** after the complete
MEGA-PR-03. It does not permit unrestricted production live or automatic limit
growth.

## CP1 implementation

`src/live_boundary/mega_pr03_live_canary_convergence.py` adds a deterministic
fail-closed checkpoint gate that requires:

- accepted, independently reviewed, release-bound MEGA-PR-02 paper evidence;
- one canonical evidence owner for signer, authorization, durable intent,
  finalized settlement, canary control, trusted time, qualification and
  realized PnL;
- explicit quarantine of superseded review-only gates and one declared
  compatibility alias;
- physically separated signer process/image and authenticated narrow IPC;
- exact canonical message binding, semantic limits and persisted anti-replay;
- durable intent before the first network side effect;
- one selected transport, no blind resend and ACK/processed/confirmed never
  counting as economic success;
- complete crash, blockhash-expiry, duplicate-send and Jito-unbundling drills;
- finalized `getTransaction` evidence with v0 support, fee/tip/rent, native and
  token deltas, inner instructions and repayment verification;
- capital lock for unknown outcomes, RPC disagreement, reorgs and external
  wallet activity;
- realized reconciled PnL as the only canary metric authority;
- one-time signed permit bound to release/config/wallet/program/provider/message;
- two independent reviewers, no self-approval and one in-flight canary;
- absolute capital, loss, fee/tip, transaction-count and slippage limits;
- restart-persistent latches and signed post-run go/no-go evidence.

A clean CP1 report permits only review of the next checkpoint:

```text
bounded_canary_review_allowed=true
live_execution_allowed=false
unrestricted_live_allowed=false
automatic_scale_up_allowed=false
```

## Canonical convergence map

CP1 recognizes the current main-branch safety surfaces as evidence authorities:

- signer/finalized settlement:
  `src.live_boundary.pr202_isolated_signer_settlement`;
- authorization/finality evidence:
  `src.pr211_signer_outbox_finality_gate`;
- durable submission intent:
  `isolated_signer_service.flashloan_isolated_signer.pr199`;
- durable canary/operator/latch control:
  `src.mpr14_durable_canary_operator_control`;
- trusted time and anti-replay:
  `src.mpr16_trusted_time_archive_gate`;
- installed deployment qualification:
  `src.mpr17_hermetic_deployment_cutover_gate`.

Historical PR-199 and MPR-07 canary gates remain review-only and cannot become
parallel runtime authorities. The old `src.submission.pr202...` path remains an
explicit compatibility alias to the canonical `src.live_boundary` module.

## Verification

```bash
PYTHONPATH=. python -m compileall -q \
  src/live_boundary/mega_pr03_live_canary_convergence.py \
  tests/test_mega_pr03_live_canary_convergence.py

PYTHONPATH=. python -m pytest -q \
  tests/test_mega_pr03_live_canary_convergence.py
```

Focused local result before the branch was created:

```text
21 passed
```

## Safety boundary

This checkpoint does not:

- load or generate a private key;
- start a signer process;
- open signer IPC;
- construct, sign or submit a transaction;
- call RPC, Jito, Jupiter, MarginFi or Kamino;
- consume a real canary permit;
- mutate durable runtime state;
- enable paper, canary or unrestricted live execution.

## Remaining checkpoint plan

### CP2 — isolated signer and bounded submission

Implement the real separated signer package/process boundary, authenticated
local IPC, protected key authority adapter, exact-message signing policy,
durable outbox integration and bounded RPC/Jito sender without treating ACK as
success.

### CP3 — finalized settlement and unknown recovery

Wire finalized v0 transaction retrieval, native/token/inner-instruction
reconciliation, authoritative fee/tip/rent/repayment accounting, unknown-state
capital locking and restart/reorg/RPC-disagreement recovery.

### CP4 — signed bounded canary and post-run evidence

Wire one-time release-bound canary permits, durable two-person approvals, hard
loss and provider/reconciliation latches, one-in-flight execution, signed
post-run evidence and manual go/no-go. Automatic scale-up and unrestricted live
remain forbidden.
