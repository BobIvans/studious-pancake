# PR-140 — Data lineage, synthetic/real labeling and artifact quarantine

This PR implements the first repository-enforced slice of roadmap **PR-140**.

The second deep audit found runtime and synthetic artifacts tracked in the
repository root. These files can pollute training, release evidence and
historical performance claims unless every dataset row has explicit lineage and
finalized settlement provenance.

## What this PR changes

- Removes tracked root runtime/generated artifacts:
  - `ai_training_data.csv`
  - `trade_history.csv`
  - `bot_health.json`
  - `helius-sanctum-lst-webhook.json`
- Extends `.gitignore` so `trade_history.csv` is also treated as generated
  runtime output.
- Adds `src/data_lineage_pr140.py`, an offline validation boundary for:
  - forbidden root artifact quarantine;
  - fixed-width CSV shape validation;
  - synthetic / recorded / live source labeling;
  - artifact SHA-256 provenance;
  - contract/config pins;
  - `actual_*` financial fields requiring finalized settlement evidence for
    recorded/live datasets.
- Adds `src/resources/data_lineage_policy_pr140.json`.
- Adds `tests/test_pr140_data_lineage_quarantine.py`.
- Wires the focused PR-140 test into `scripts/verify_repo.py` and adds the new
  Python files to `config/format_targets.txt`.

## Safety boundary

This PR does not claim that any historical trading row is real trading
evidence. The default admission remains:

```text
blocked_until_lineage_manifest_and_settlement_evidence
```

Synthetic datasets may still exist outside the repository, but they must be
explicitly labeled as synthetic and excluded from financial performance metrics.
Recorded/live rows that contain `actual_*` fields require finalized settlement
evidence before they can be treated as performance evidence.

## Non-goals

- No live submission enablement.
- No model training integration.
- No PR-138 settlement implementation.
- No history rewrite; this PR removes the files from the current tree and adds
  a gate so they do not return.

## Verification

```bash
python -m pytest tests/test_pr140_data_lineage_quarantine.py -q
python scripts/verify_repo.py --skip-dependency-audit
```
