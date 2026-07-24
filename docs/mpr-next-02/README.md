# MPR-NEXT-02 — Physical canonical paper/shadow vertical cutover

This branch starts the implementation track for **MPR-NEXT-02**.

## Goal

Turn the current paper/shadow scaffolding into one physical sender-free runtime vertical.

The target runtime path is:

```text
provider evidence
→ opportunity
→ feasibility
→ planning
→ compilation proof
→ exact simulation
→ terminal paper outcome
→ reconciliation
→ durable event projection
```

## Non-goals

- Do not enable live trading.
- Do not read private keys.
- Do not sign or submit transactions.
- Do not treat synthetic provider input as production evidence.

## Initial implementation checklist

- [ ] Add installed CLI path: `flashloan-bot run --mode paper --json`.
- [ ] Preserve one canonical attempt identity through all stages.
- [ ] Make exact simulation mandatory before paper outcome.
- [ ] Make reconciliation mandatory before success.
- [ ] Separate `healthy_idle`, `no_candidate`, `rejected_candidate`, `stage_blocked`, `simulated_paper_success`, `simulated_paper_failure`, and `reconciliation_mismatch`.
- [ ] Fail closed when provider evidence is missing or synthetic.
- [ ] Add deterministic replay and restart-recovery tests.
- [ ] Keep production debt open until materialized evidence artifacts exist.
