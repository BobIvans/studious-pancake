# Source package traceability

The implementation is grounded in the supplied `MPR_2618_CREDENTIAL_TRUST_ROTATION_REVOCATION_PACKAGE`.

Package-mandated reproduced gaps addressed in this branch:

- C2618-01: a previously issued secret handle must fail future supported use after durable revoke;
- C2618-02: one logical secret must have one canonical preferred generation except for an explicit bounded overlap;
- C2618-03: an old trust-registry snapshot must not authorize a new sensitive action after the durable current generation/revocation epoch advances.

The package also requires default-off behavior, no secret values in lifecycle/evidence state, no real private-key export, no mainnet sends from CI, and discovery of MPR-2617 before shared ownership is assumed. Those constraints are preserved here.
