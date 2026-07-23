# MPR-CLOSE-03 — provider/protocol rooted data plane

This draft branch is intentionally cut from `main` and scoped to the verifier/evidence layer for MPR-CLOSE-03.

## What this patch does now

- adds repository-native verifier primitives in `src/mpr_close_03_verifiers.py`;
- adds three runnable scripts:
  - `scripts/verify_solana_v0_alt_conformance.py`
  - `scripts/verify_external_contracts.py`
  - `scripts/verify_provider_drift_probes.py`
- adds focused regression coverage in `tests/test_mpr_close_03_verifiers.py`;
- adds a dedicated workflow `.github/workflows/mpr-close-03-provider-protocol.yml`.

## What this patch does not claim yet

This branch does **not** claim complete closure of MPR-CLOSE-03.
It does not enable live send, signer access, or provider credential promotion.
It is meant to surface the exact blockers still remaining in the repository so the next commits can wire the runtime data plane against explicit evidence instead of broad assumptions.

## Follow-up expected on top of this branch

1. Materialize strict Solana `maxSupportedTransactionVersion` reads for v0 settlement evidence.
2. Bind Helius authenticated ingress + rooted recovery into one runtime admission path.
3. Tighten `external_contracts.json` and related manifests so missing artifacts shrink to reviewed evidence only.
4. Move MarginFi and Kamino from blocked documentation state to reviewed conformance state only when real artifacts exist.
