# PR-125 — LST universe, oracle/redemption and asset-governance policy

This patch implements an offline, fail-closed LST governance boundary. It does
not enable live trading, redemption, unstake, sender, signer, RPC submission, or
Jito bundle behavior.

## What changed

- Adds `src/lst_governance_pr125.py`:
  - validates the committed LST governance contract;
  - separates circular DEX arbitrage from LST fair-value/depeg and
    redemption/unstake strategies;
  - evaluates JitoSOL, mSOL and bSOL as LST assets;
  - requires reviewed mint provenance, oracle model, redemption model and
    deployment attestation before any LST execution can be considered ready;
  - keeps optional LST discovery pairs disabled by default.
- Adds `src/resources/lst_governance_pr125.json`:
  - records the policy shell for JitoSOL, mSOL and bSOL;
  - sets all asset exposure caps to zero by default;
  - requires oracle+redemption evidence for fair-value decisions;
  - models depeg and abnormal-redemption kill-switch gates.
- Adds `tests/test_pr125_lst_governance_policy.py`.
- Wires the focused test into `scripts/verify_repo.py` and adds the new Python
  files to `config/format_targets.txt`.

## Safety properties

- A DEX circular quote is never accepted as the only fair-value source for an
  LST strategy.
- Optional LST pairs remain disabled until reviewed evidence exists.
- Required LST pairs are policy blockers.
- No LST asset is executable without reviewed:
  - official mint provenance;
  - oracle model;
  - redemption/exchange-rate model;
  - deployment/authority attestation.
- Default LST exposure caps are zero.

## Verification

Focused verification:

```bash
python -m pytest tests/test_pr125_lst_governance_policy.py -q
python -m src.lst_governance_pr125 --repo-root . --json
python -m src.lst_governance_pr125 --repo-root . --require-lst-execution-ready
# expected non-zero until reviewed evidence is committed
```

Repository verification:

```bash
python scripts/verify_repo.py --skip-dependency-audit
```

## Non-goals

- No official-source attestation is claimed in this PR.
- No redemption or oracle adapter is implemented.
- No on-chain read path is added.
- No live/paper execution path is enabled.
- No PR-124 program deployment attestation is duplicated here.
