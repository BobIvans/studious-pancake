# MEGA-PR D — release/soak/canary preflight

This starts a safe executable slice for **MEGA-PR D — Real paper soak,
immutable release evidence and reviewed limited canary**.

The workplan says PR D requires real non-synthetic sender-free soak, release
artifacts generated from the actual candidate build, runtime hardening evidence,
operational rehearsal and a tiny manually reviewed canary policy. This PR does
not fabricate any of those artifacts and does not enable live.

## Added

- `src/release_soak_canary_prd.py`
- `scripts/prd_release_soak_preflight.py`
- `tests/test_prd_release_soak_canary_preflight.py`

## Behavior

`python scripts/prd_release_soak_preflight.py` prints a JSON report and exits
non-zero unless real evidence is supplied. The default report blocks on:

- missing soak evidence;
- missing release artifacts;
- missing canary limits.

Even with complete evidence, `live_enabled` remains `false` and manual review is
required.

## Non-goals

- no signer or sender wiring;
- no RPC/Jito/Jupiter/Helius/MarginFi calls;
- no fake signatures, bundle IDs, or settlement status;
- no claim that real soak has already run;
- no automatic live/canary enablement.
