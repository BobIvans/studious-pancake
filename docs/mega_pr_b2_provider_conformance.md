# MEGA-PR B2 — Real provider evidence, adapters and ingestion

This PR starts the producer-to-consumer external-conformance vertical required by the production-ready workplan.

It does not claim that protected provider probes have already been run. It adds the runtime-owned schema, adapter ports, manual/protected probe plans, redacted fixture writer and admission controller that make real probes consumable by MEGA-PR A without permitting documentation-only admission.

## Active surfaces

Added package:

```text
src.providers.conformance
```

The package provides:

- one canonical `ExternalEvidenceBundle` schema;
- redacted fixture hashing/writing;
- fail-closed admission with expiry, drift, credential failure, program identity change and RPC quorum disagreement revocation;
- active runtime ports for the MEGA-PR A dependency factory;
- a Jupiter Swap V2 `/swap/v2/build` adapter port that rejects legacy endpoint assumptions;
- a rooted Solana RPC evidence service;
- a read-only Jito adapter that permits `getTipAccounts` and rejects submission methods;
- deployed-program observation validation for MarginFi/future Kamino evidence;
- `python -m src.providers.conformance.mega_b2 plan` for protected workflow probe planning;
- `python -m src.providers.conformance.mega_b2 replay --bundle ...` for offline fixture/admission replay.

## Safety invariants

No live trading, sender, signing, submission or private-key path is added. Documentation review alone blocks admission; missing protected probe blocks admission; expired/drifted evidence blocks admission.
