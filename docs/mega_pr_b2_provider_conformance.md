# MEGA-PR B2 — Real provider evidence, adapters and ingestion

This PR starts the producer-to-consumer external-conformance vertical required by the production-ready workplan.

It does not claim that protected provider probes have already been run. It adds the runtime-owned schema, adapter ports, manual/protected probe plans, redacted fixture writer and admission controller that make real probes consumable by MEGA-PR A without permitting documentation-only admission.

## Active surfaces

Added package:

```text
src.providers.conformance
```

The package provides one canonical `ExternalEvidenceBundle` schema, redacted fixture hashing/writing, fail-closed admission with expiry/drift/credential/program/RPC revocation, active runtime ports for MEGA-PR A, a Jupiter Swap V2 `/swap/v2/build` adapter port, rooted Solana RPC evidence service, read-only Jito `getTipAccounts`, deployed-program observation validation, and CLI plan/replay commands.

## Safety invariants

No live trading, sender, signing, submission or private-key path is added. Documentation review alone blocks admission; missing protected probe blocks admission; expired/drifted evidence blocks admission.
