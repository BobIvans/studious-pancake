# MPR-CLOSE-02 — runtime cutover start

This branch starts **MPR-CLOSE-02** from current `main` as an isolated reviewable slice.

## Goal

Move the repository toward one physical sender-free paper/shadow runtime vertical owned by the installed CLI, while keeping:

- `live_enabled = false`
- `signer_loaded = false`
- `sender_loaded = false`
- `product_state = not-production-ready`

## Required end-state for the full PR

The final MPR-CLOSE-02 implementation should converge on one composition root for:

- `flashloan-bot run --mode paper --dry-run --json`
- `flashloan-bot run --mode shadow --dry-run --json`
- `flashloan-bot status --json`
- `flashloan-bot readiness --json`

The physical sender-free cycle must be:

```text
provider/discovery snapshot
-> normalized candidate
-> deterministic opportunity_id
-> feasibility policy
-> capital/rent/fee reservation
-> account lifecycle plan
-> canonical transaction plan
-> instruction firewall / transaction proof
-> exact final message hash
-> exact simulation record or fail-closed reason
-> durable terminal lifecycle state
-> paper/shadow result JSON
```

## Non-goals for this start branch

This start branch must not:

- enable live trading;
- load a signer;
- load a sender transport;
- load a private key;
- add Jito submission;
- claim paper-ready or production-ready state.

## Exact invariants to preserve

1. **One composition root only**
   - installed CLI remains the user-visible entrypoint;
   - legacy wrappers may delegate, but must not own separate runtime logic.

2. **Exact simulation binding**
   - the message that is simulated must be the message referenced by the terminal paper/shadow result;
   - mutation after simulation must fail closed.

3. **Small-capital fail-closed economics**
   - ATA creation;
   - WSOL wrap/unwrap;
   - rent exemptions;
   - priority fee;
   - bundled tip when present in paper proof;
   - flashloan fees;
   - dust reserve.

   These costs must be reserved before net-positive paper acceptance is allowed.

4. **Lineage discipline**
   Every result must carry exactly one lineage class:

   - `synthetic_fixture`
   - `recorded_provider_fixture`
   - `credentialed_provider_snapshot`
   - `finalized_onchain_evidence`

   Only credentialed or finalized evidence may contribute to future promotion reports.

## Acceptance target for the eventual full implementation

```bash
python -m compileall -q arb_bot.py src scripts tests
python scripts/verify_installed_artifact.py --json
python scripts/verify_mpr01_runtime_cutover.py --json
python -m pytest -q \
  tests/test_mega_pr01_canonical_runtime_paper_core.py \
  tests/test_mega_pr01_canonical_paper_platform.py \
  tests/test_pr_a_canonical_paper_vertical.py \
  tests/test_pr131_account_lifecycle.py
```

## Parallel-work note

This branch was created directly from `main` to avoid overwriting parallel PR work already in flight. It is intended to become the dedicated review thread for the MPR-CLOSE-02 cutover sequence.
