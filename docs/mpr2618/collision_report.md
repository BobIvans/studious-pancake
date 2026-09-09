# MPR-2618 collision report

Observed implementation base:

- `main`: `d23f82e20d10345926742352739b1a6ca3f7a859` (includes merged MPR-2611 / PR #482).
- public `codex/mpr-2612-final-release-gate` exists.
- public `codex/mpr-2613-guarded-production-operations` exists.
- MPR-2615 is PR #486 and owns controlled multi-lender expansion.
- MPR-2617 appeared after the initial 2618 preflight as PR #489 / `codex/mpr-2617-direct-venue-execution-expansion`.
- no public MPR-2614 or MPR-2616 branch was observed in the checked repository searches.
- legacy `pr-112-emergency-credential-incident-response` and `pr-183-credential-lifecycle-trust-anchors` exist and are treated as predecessor concepts, not duplicated wholesale.

## MPR-2617 semantic reconciliation

PR #489 owns direct-venue capability and Orca qualification: exact venue/program/pool/mint/deployment/math/evidence binding, route admission and venue-specific qualification. It explicitly does not reimplement provider governance, release, signer/submission, canary or economic authorities.

No credential lifecycle, trust-root rotation, KMS/HSM recovery, compromise-response or revocation-propagation ownership was observed in #489. Therefore MPR-2618 and MPR-2617 are semantically disjoint at the observed heads. MPR-2618 does not import, duplicate or modify MPR-2617 paths.

This reconciliation must be repeated only if #489 materially changes into credential/trust ownership before merge.
