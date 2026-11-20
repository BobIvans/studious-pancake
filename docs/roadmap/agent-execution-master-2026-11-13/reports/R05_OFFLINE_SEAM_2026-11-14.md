# R05-S — offline unsigned-plan simulation seam (lane report)

**Lane:** R05-S (wave-3). **Implemented:** 2026-11-19/20. **Base:** main `857daea9`
(worktree branch `agent/r05-unsigned-sim-seam`, one focused commit).

## What this lane is (and deliberately is not)

NEW read-only seam `src/execution/unsigned_plan_simulation_seam.py` converting
R-03 unsigned builder plans into the exact-simulation INPUT shape
(`src/execution/models.PlannedInstruction` records — the payload the
`ExactSimulationFinalizer` consumes inside a `TransactionPlan`) for:

- **Jupiter Lend / Kamino (Solana bookends):** byte-preserving conversion —
  `bytes.fromhex(bookend.data_hex)` is the single source; sha256 receipts
  before/after enforced; account-meta order/flags preserved; discriminator
  prefixes intact.
- **Kamino golden bytes** (`tests/fixtures/r03/kamino_flash_abi_golden.json`,
  pinned klend-sdk 13.0.2): `convert_kamino_golden_fixture` converts both
  flash bookends with typed provenance. The program-settled flash fee is NOT
  encoded in instruction data → required repayment stays UNKNOWN (`None`,
  never zero).
- **NAVI (Sui PTB):** evidence-only conversion under the typed surface state
  `SUI_PTB_OUT_OF_SOLANA_SIMULATION_SCOPE` — the exact simulation owner is
  Solana/Solders-only; PTB commands are fingerprinted (canonical receipts),
  never re-encoded into Solana shapes.

## What the seam does NOT do

- No compilation, no signing, no sending, no RPC of any kind (structurally
  tested: the module never imports `exact_simulation` or an RPC client).
- No payer/signers fabricated: the R-03 contract is sender-free; the seam
  stops at instruction records and declares the frozen missing-context tuple
  `(payer, blockhash_context, state_evidence, rpc_authority)`.
- No state evidence: every record carries `state_evidence=None` and the typed
  gate reason **`SIM_SEAM_STATE_EVIDENCE_REQUIRED`**; the deterministic
  verdict `simulation_state_verdict()` is always
  `BLOCKED / SIM_SEAM_STATE_EVIDENCE_REQUIRED / qualified_plan_count=0` —
  there is no code path returning a qualified verdict. **R-05 stays BLOCKED**;
  the seam does not claim qualification (literal
  `is_qualified_for_exact_simulation == False`).
- Blocked R-03 plans (e.g. Jupiter Lend `BLOCKED_INPUT_REQUIRED` /
  `NEEDS_ACCOUNT_SETUP`) are never converted — nothing is fabricated; typed
  blockers are preserved in the error detail.

## Exact changed paths

- `src/execution/unsigned_plan_simulation_seam.py` — NEW seam owner.
- `tests/test_r05_simulation_seam.py` — NEW tests (13).
- `docs/roadmap/agent-execution-master-2026-11-13/reports/R05_OFFLINE_SEAM_2026-11-14.md` — this report.
- `config/format_targets.txt` — seam appended (CI black gate).
- `src/execution/exact_simulation.py` and `src/lending/unsigned_builders/*` UNTOUCHED.

## Build ≠ capacity ≠ simulation

The seam imports the frozen R-03 contract enums and the kernel-adjacent
`PlannedInstruction` type only; it adds no capacity member, no execution-ready
state and no qualification authority. Providers remain disabled; live/sign/send
hard-denied; fixtures are never live evidence.

## Test evidence (offline, pytest-socket)

- `tests/test_r05_simulation_seam.py`: 13 tests — byte preservation (golden
  bytes identical, meta order/flags, discriminators, corrupted-fixture
  refusal), typed provenance, unknown-repayment-as-None, blocked-plan
  refusal, Sui scope boundary, hot-potato contract still enforced, frozen
  missing-context declaration, always-BLOCKED verdict, structural no-RPC check.
- Exact counts recorded in the PR body at open time.

## Blockers / deferred

- Live state evidence (payer context, blockhash, governed RPC) remains
  explicitly missing — R-05 stays BLOCKED until a user-gated capture lane.
- Assembling a full `TransactionPlan` + running `ExactSimulationFinalizer` is
  NOT part of this seam (a later lane owns live context, if ever authorized).
- Next lane in wave-3 order: R08-step1 governed-RPC composition seam.
