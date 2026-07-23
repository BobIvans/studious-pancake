# MEGA-PR-02 — Production paper qualification contract

## Purpose

This checkpoint starts **MEGA-PR-02: Protocol correctness, hermetic release and production paper qualification**.

The branch adds one sender-free qualification contract under a stable domain path:

- `src/release_gate/production_paper_qualification.py`
- `tests/test_production_paper_qualification.py`

It deliberately does not add live trading, signer access, transaction submission, provider network calls or a new GitHub Actions workflow.

## Dependency boundary

MEGA-PR-02 depends on MEGA-PR-01. The evaluator therefore requires:

- accepted MEGA-PR-01 evidence;
- a non-placeholder MEGA-PR-01 report digest;
- the exact sender-free release identity qualified by this checkpoint.

A missing MEGA-PR-01 acceptance produces `MEGA_PR_01_NOT_ACCEPTED`.

## Qualification workstreams

### 1. Protocol conformance

The required admitted protocol set is exact:

- Solana v0 RPC;
- Jupiter Swap;
- MarginFi v2;
- Kamino KLend.

Each protocol requires materialized credentialed probes, golden fixtures, negative fixtures, schema pinning, program/account identity validation and drift evidence. Jupiter contract generation must be unambiguous. Optional providers remain disabled unless separately admitted.

### 2. Exact message, simulation and economics

The compiled v0 message hash must equal the simulated message hash. The qualification contract requires:

- immutable post-simulation message identity;
- exact instruction ordering;
- program allowlist;
- account metas;
- signer/writable flags;
- compute-budget policy;
- blockhash validity;
- complete fees, rent and tips reservation;
- slippage, flash repayment and minimum-profit proof.

Any mismatch blocks paper promotion.

### 3. Hermetic release

The release proof binds:

- clean source commit/tree;
- wheel;
- image;
- configuration;
- provider contracts;
- qualification manifest;
- SBOM;
- provenance;
- artifact signature.

It requires a network-disabled build from an offline hash-locked wheelhouse, full 40-character GitHub Action SHAs, a digest-pinned Docker base and equal admitted surface between wheel and image.

### 4. Enforced sandbox and operator security

The qualification evidence must prove at runtime:

- non-root execution;
- read-only root filesystem;
- loaded and hash-verified AppArmor/seccomp profiles;
- denied write/capability/egress scenarios;
- destination/port/DNS egress allowlisting;
- secrets from files or a manager only;
- secret rotation drill;
- authenticated RBAC operator plane;
- durable audit log;
- pause/drain/kill-switch and break-glass drills.

Static declarations alone are not enough for final completion.

### 5. Release-bound 72-hour soak

The soak must last at least 72 hours and bind to the exact wheel, image, config and provider-contract digests. It requires:

- non-synthetic streaming data;
- real provider data plane;
- zero synthetic contamination;
- the complete chaos matrix;
- zero lost or duplicate intents;
- zero unexplained terminal states;
- complete causal/economic evidence for accepted cycles;
- SLOs for provider availability, rooted freshness, latency, queue/cycle completion and reconciliation;
- materialized resource profiles;
- alert/runbook drills;
- immutable signed evidence and independent review.

## Safety boundary

A passing report may allow only:

```text
paper_ready_allowed=true
```

It always returns:

```text
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
```

This checkpoint does not include a signer, key loader, sender, RPC/Jito submission, canary permit or live capability.

## Focused verification

```bash
PYTHONPATH=. python -m py_compile \
  src/release_gate/production_paper_qualification.py \
  tests/test_production_paper_qualification.py

PYTHONPATH=. python -m pytest -q \
  tests/test_production_paper_qualification.py
```

Expected result:

```text
17 passed
```

## Remaining MEGA-PR-02 implementation

This checkpoint is the strict acceptance contract, not the full completion of MEGA-PR-02. Follow-up commit sets on the same mega branch must still:

1. collect real credentialed protocol evidence;
2. make the exact-message proof the runtime authority;
3. build the clean offline wheel/image and provenance chain;
4. execute real sandbox and egress tests;
5. run the release-bound 72-hour non-synthetic soak;
6. connect the resulting immutable evidence bundle to the installed release qualification CLI;
7. prove that source, wheel and image use the same sender-free composition root.

Paper-ready must remain blocked until those materialized collectors and drills satisfy this contract.
