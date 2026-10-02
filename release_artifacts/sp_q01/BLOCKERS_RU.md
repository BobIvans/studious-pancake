# SP-Q01 blockers — current truth

## Closed by this PR

The installed resolver could previously trust `qualified=true` plus an opaque
SHA after checking only lender/program/generation identity. The SHA did not
prove what source, deployed programdata, rooted accounts, build, freshness or
human review it represented.

This PR requires a v2 manifest whose qualified Jupiter Lend PRIMARY and Slumlord
RENT identities carry a structured admission receipt. The receipt is bound to
the existing `evidence_sha256`.

## Still BLOCKED_EXTERNAL

1. A current rooted Jupiter Lend Flashloan deployment/programdata observation.
2. A current rooted FlashloanAdmin PDA observation for the same evidence window.
3. A verified Jupiter build artifact hash bound to the deployed programdata.
4. A current rooted Slumlord program/PDA observation.
5. Slumlord build/program hash evidence for the same evidence generation.
6. Human review of the exact evidence bundle.
7. Current governed provider/RPC evidence and the later loaded-state repayment
   decoder qualification already tracked by existing AGG/SUPER owners.

These are not fabricated by this code change. Until supplied, operational
qualification remains blocked.

MarginFi remains PAUSED. No sign/send/withdraw/live effect is added.
