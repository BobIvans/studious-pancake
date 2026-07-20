# PR-034 — Atomic MarginFi + Jupiter two-leg planner

## Status

This PR is intentionally opened as a **draft** and synchronized directly to the
current `main` baseline
`d2a387e114726befcfe02393dac9c39da58fe576`.

It creates the isolated planning boundary for the first supported atomic route:

```text
Jupiter setup
→ MarginFi start_flashloan
→ MarginFi borrow
→ Jupiter leg A other/swap
→ Jupiter leg B other/swap
→ MarginFi repay
→ Jupiter cleanup
→ MarginFi end_flashloan
```

No signer, sender, permit, simulation-success claim, live toggle, or submission
path is added.

## Why this is isolated from parallel PRs

PR-028, PR-031, PR-032, PR-033 and PR-035 are being developed in parallel.
This branch therefore adds a new `src.planning` package and does not edit files
owned by those PRs. PR-027 and PR-029 are already merged into the base. The
planner consumes structural ports/evidence that the remaining PRs must satisfy
after they are merged:

- PR-028: a MarginFi provider with `execution_conformance_verified is True`,
  pinned SHA-256 provenance, integer repayment, and deterministic
  `prepare`/`finalize` instructions;
- PR-031: canonical account-wide Jupiter quota/finalization scheduling;
- PR-032: capital approval/reservation evidence for the exact borrow amount;
- PR-033: an immutable candidate ID plus slot-consistent discovery evidence;
- PR-035: hardened v0 compilation/ALT/blockhash proof downstream of this plan.

The current quarantined MarginFi implementation on `main` does not expose the
required conformance bit. Consequently, production use fails closed until the
verified PR-028 implementation is synchronized into this branch.

## Planner contract

`AtomicMarginfiJupiterPlanner.plan()` accepts:

- one payer/authority `Pubkey`;
- one coherent MarginFi snapshot;
- an integer borrow amount;
- destination and repayment token accounts;
- exactly two canonical `JupiterInstructionBundle` values;
- capital reservation evidence bound to the same borrow amount;
- a reviewed Jupiter contract SHA-256 pin;
- discovery/oracle slots and a non-negative repayment surplus;
- an immutable program allowlist and instruction ceiling.

It returns:

- one typed `TransactionPlan` for the canonical PR-029/v0 compiler boundary;
- exact start/end positions and cleanup count;
- required repayment and guaranteed second-leg output;
- deterministic route, sequence, capital, contract, slot and ALT provenance.

## Enforced invariants

### Route and economics

- both legs are `ExactIn`;
- leg A starts with the selected MarginFi bank mint and exact borrow amount;
- leg A output mint equals leg B input mint;
- leg B returns to the selected MarginFi bank mint;
- leg B input cannot exceed leg A guaranteed minimum output;
- leg B guaranteed output must cover at least principal plus the configured
  safety surplus before MarginFi preparation;
- the verified MarginFi provider's exact repayment must also fit within the
  same guaranteed output;
- binary float money is never accepted by this boundary.

### Atomic instruction order

- Jupiter setup stays before `start_flashloan`;
- the MarginFi provider inserts exactly one start and one end instruction;
- borrow precedes both swaps;
- leg A provider `other` instructions stay adjacent to leg A;
- leg B provider `other` instructions stay adjacent to leg B;
- repay precedes cleanup;
- cleanup remains inside the atomic transaction but after repayment;
- `end_flashloan` is the final application instruction;
- any mutation or index mismatch fails with `PR034_SEQUENCE_INVARIANT`.

Cleanup is deliberately placed after repayment. This avoids closing or
unwrapping a repayment source before the debt has been repaid. PR-036/037 must
still simulate and reconcile cleanup/rent/token effects before any promotion.

### Ownership and safety

- provider-supplied compute-budget instructions are forbidden;
- provider-supplied tips are forbidden;
- the compiler/sender remain the sole owners of CU and tip policy;
- every final program ID must be in the configured allowlist;
- the first vertical requires payer == MarginFi authority;
- no instruction may require an additional signer;
- stale/future-dated Jupiter builds fail closed;
- conflicting ALT contents for the same ALT address fail closed;
- invalid ALT/account pubkeys fail closed;
- the plan contains no live authority and cannot submit anything.

## Provenance

The result records deterministic SHA-256 fingerprints for:

- the reviewed Jupiter contract pin;
- the verified MarginFi pin and state snapshot;
- each complete Jupiter build bundle;
- the finalized instruction sequence;
- the capital decision and reservation;
- the full PR-034 provenance envelope.

The fingerprints are evidence bindings, not proof of profitability or on-chain
success. Exact v0 compilation, final-message simulation, fee calculation and
economic reconciliation remain PR-035 through PR-037.

## Tests

`tests/test_pr034_atomic_marginfi_jupiter.py` covers:

- the exact successful instruction order and roles;
- signer, ALT and slot propagation into `TransactionPlan`;
- deterministic provenance;
- default denial for an unverified MarginFi provider;
- insufficient guaranteed intermediate balance;
- insufficient guaranteed repayment output;
- provider-owned compute/tip rejection;
- stale build rejection;
- program allowlist rejection;
- conflicting ALT provenance rejection.

Focused verification:

```bash
python -m compileall -q src/planning tests/test_pr034_atomic_marginfi_jupiter.py
python -m pytest tests/test_pr034_atomic_marginfi_jupiter.py -q --disable-socket
```

Repository verification remains:

```bash
python scripts/verify_repo.py
```

## Merge blockers

- [x] PR-027 external-contract registry is merged into this branch's base.
- [x] PR-029 canonical execution-domain boundary is merged into this branch's
      base; the planner emits its typed `TransactionPlan`/Solders instructions.
- [ ] PR-028 is merged, synchronized, and exposes an explicit verified
      conformance admission only after offline and read-only mainnet assertions.
- [ ] PR-031 canonical Jupiter quota/finalization output is synchronized without
      weakening the planner's freshness or provider-ownership rules.
- [ ] PR-032 is merged and an adapter binds its actual atomic reservation to
      `CapitalReservationEvidence`.
- [ ] PR-033 candidate/snapshot output is connected without weakening slot or
      freshness checks.
- [ ] Focused tests and full repository verification pass after synchronization.
- [ ] Human review confirms MarginFi start/end index semantics and Jupiter
      setup/other/swap/cleanup ordering against the final pinned contracts.

PR-035 can proceed independently and later consume this PR's typed plan; it is
not a prerequisite for reviewing PR-034, but both must be synchronized before
the PR-036 exact-simulation stage.

## Non-goals

- compiling v0 messages or resolving live ALT accounts (PR-035);
- compute finalization or exact simulation (PR-036);
- SPL/Token-2022/native repayment and P&L reconciliation (PR-037);
- paper runner composition (PR-038);
- signing, RPC/Jito submission, live permits or live activation;
- OKX, OpenOcean, Odos, Pump, orderbook, Kamino or liquidation execution.
