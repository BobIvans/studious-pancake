# MPR-NEXT-13 — Release workflow supply-chain hardening

This branch starts the dedicated review surface for **MPR-NEXT-13** from the fourth-pass production-ready audit.

## Goal

Make CI and release evidence hermetic enough that workflow execution, release artifacts, and production-debt closure cannot rely on mutable GitHub Action tags, mutable release inputs, or unsigned/unpinned evidence.

## Initial scope for follow-up implementation

- Pin all GitHub Actions `uses:` references to full commit SHAs.
- Add an allowed-action-digest policy file.
- Add a CI test rejecting floating action tags.
- Add SBOM/image/wheel/config digest bundle as release artifacts.
- Ensure PR-225, PR-226, PR-228, MPR-29, MPR-30, and MPR-31 run in release qualification.

## Safety boundary

This start slice does not enable live trading, signing, transaction submission, Jito, canary arming, or production-ready promotion.

## Intended acceptance checks

```bash
python scripts/check_workflow_action_pins.py
python scripts/production_debt_audit.py --json
```
