# PR-219 — Canonical Product, Artifact and Quality Truth gate

This checkpoint turns the PR-219 roadmap scope into a deterministic,
side-effect-free evidence contract.  It does not build wheels, mutate
configuration, inspect a host, load a key, sign, send, or enable live trading.

## Scope

The gate covers the PR-219 ownership group from the 409-finding roadmap:
canonical product authority, one CLI/composition root, installed wheel closure,
architecture retirement, typed configuration, hermetic dependency/release truth,
CI truth and installed behavioral quality.

## Safety boundary

The report always returns:

```text
live_execution_allowed=false
sender_allowed=false
signer_allowed=false
```

A green report only means that PR-220 and PR-221 are unblocked from depending on
one canonical sender-free checkout/wheel/release truth.  It is not a paper-trade,
signer or live-trade permit.

## Required follow-up cutover

This first checkpoint intentionally avoids risky mass deletion.  The remaining
PR-219 work must materialize the evidence consumed by the gate:

1. build the main and signer wheels as one release set;
2. compare root launcher and installed console contracts;
3. generate installed reachability and required-control traces;
4. retire duplicate schemas/enums/authorities and version-by-filename selection;
5. create one immutable typed config snapshot and signed activation policy;
6. pin Actions/base images and publish SBOM/provenance;
7. enforce coverage, mypy, lint, black and no-production-assert gates over the
   installed graph.
