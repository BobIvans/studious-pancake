# MPR-NEXT-06 — Shadow soak, MPR-29/MPR-30 and final promotion evidence

This slice adds a fail-closed, offline foundation for the final promotion evidence program.
It does not enable live trading, private-key access, transaction submission or unrestricted canary behavior.

## Purpose

MPR-NEXT-06 exists to prevent final promotion from being satisfied by in-memory DTOs,
synthetic fixtures or transport acknowledgements. The boundary requires:

- MPR-29 continuous non-synthetic paper/shadow soak evidence;
- MPR-30 default-off signer, Jito and finalized reconciliation evidence;
- MPR-31 artifact-only consumption of signed immutable evidence from MPR-25 through MPR-30;
- release bundle artifacts for source, wheel, image, SBOM, config, policy, provider contracts, soak, crash, backup/restore, secret drill and finalized economics;
- production-debt closure only through signed immutable artifacts.

## Safety invariants

- `unrestricted_live_allowed` is always false.
- `production_ready_claimed` is always false in this foundation slice.
- Jito ACK or bundle ID is never proof of landing, finality or profit.
- Unknown outcomes must remain frozen/manual-review; they cannot auto-resend.
- Soak evidence shorter than 72 hours, synthetic, unreplayed, unresolved P0/P1, or missing lineage separation is blocked.
- Any unsigned, unreviewed, mutable or synthetic artifact blocks final-promotion review.

## Verification

```bash
python -m compileall -q src/mpr_next_06_shadow_soak_final_promotion.py \
  scripts/verify_mpr_next_06_shadow_soak_final_promotion.py \
  tests/test_mpr_next_06_shadow_soak_final_promotion.py
python scripts/verify_mpr_next_06_shadow_soak_final_promotion.py --strict --json
python -m pytest -q tests/test_mpr_next_06_shadow_soak_final_promotion.py
```

## Follow-up wiring

Later implementation work should wire this contract into the physical MPR-29 soak runner,
MPR-30 submission/finality evidence generator, MPR-31 release qualification loader and
`production_debt_audit --require-ready` artifact closure path. This PR deliberately keeps
that promotion default-off until real signed evidence exists.
