# PR-209 exact atomic message semantics and economics gate

This slice implements an additive, side-effect-free acceptance gate for the Pass
6 **PR-209 — Exact Atomic Message Semantics and Economics** work package.

## Boundary

The gate is intentionally not a runtime cutover. It does not talk to Solana,
Jupiter, MarginFi, Kamino, RPC, Jito, wallets or signer processes. It is an
offline contract that future PR-208/209 runtime code must satisfy before any
compiled message can be considered safe for sender-free paper proof.

A passing report still hard-codes:

```text
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
```

## Covered findings

The validator maps the Pass 6 PR-209 findings into deterministic blockers:

- expired or near-expired blockhash evidence;
- unknown, duplicate or missing top-level instruction roles;
- missing one-to-one decoded semantic effects;
- decoded effect amounts that disagree with integer economics;
- repayment that does not equal `principal + flash_fee`;
- simulation success combined with an error code;
- simulation proof without explicit `sigVerify=true` / local signature binding;
- provider/quote/blockhash/compile/simulation timestamp ordering and freshness;
- projected fee that is not the exact total transaction fee;
- failed landed transaction evidence that tries to use a caller-supplied zero fee.

## Acceptance added by this PR

- `src/execution/pr209_exact_atomic_semantics_gate.py` defines the immutable
  evidence model and deterministic report.
- `tests/test_pr209_exact_atomic_semantics_gate.py` covers the happy path and
  adversarial fail-closed cases from the audit.
- `.github/workflows/pr209-exact-atomic-semantics-gate.yml` runs focused compile
  and pytest checks.

## Non-goals

This PR does not enable live trading, signing, submission, transaction assembly,
provider calls, protocol account fetching or production database migrations. It
is a reviewable safety contract for the later exact atomic kernel cutover.
