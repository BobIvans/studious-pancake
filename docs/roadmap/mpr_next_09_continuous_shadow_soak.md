# MPR-NEXT-09 — Continuous installed paper/shadow soak producer

## Goal

Implement the missing MPR-29 upstream evidence producer required by MPR-31 while keeping the runtime default-off.

The fourth-pass production audit identified MPR-29 as the continuous paper/shadow soak artifact that must exist before final promotion can become reachable. This PR adds the offline evidence contract and verifier, not a live runtime.

## Safety boundary

MPR-29 evidence is accepted only when:

- it is produced from the installed artifact command surface;
- it is not source-checkout-only;
- paper and shadow modes are present, but live mode is not advertised;
- provider snapshots are non-synthetic and replayable;
- lifecycle outcomes remain sender-free and submission-free;
- lineage separates synthetic, recorded and finalized data;
- the soak remains manual or scheduled and cannot auto-promote.

The accepted evidence kind is:

```text
continuous-paper-shadow-soak
```

This is the kind already allowed by MPR-31 for upstream MPR evidence.

## Non-goals

- No live trading.
- No signer loading.
- No sender or Jito submission.
- No production-ready state transition.
- No long-running soak in pull-request CI.

## Suggested checks

```bash
python -m compileall -q src/release_gate/mpr29_continuous_shadow_soak.py scripts/verify_mpr29_continuous_shadow_soak.py tests/test_mpr29_continuous_shadow_soak.py
PYTHONPATH=. python -m pytest -q tests/test_mpr29_continuous_shadow_soak.py
python scripts/verify_mpr29_continuous_shadow_soak.py --json
PYTHONPATH=. python scripts/production_debt_audit.py --json
```
