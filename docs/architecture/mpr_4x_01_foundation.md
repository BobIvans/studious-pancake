# MPR-4X-01 — canonical architecture and schema foundation

## Decision

`src.contracts.registry` is the only installed schema-registry authority. The packaged `src/resources/schema_registry.json` is its only registry resource. Canonical JSON and schema-separated hashing remain owned by `src.kernel`.

## Active cutover

`src.release.identity.ReleaseGenerationIdentity` no longer owns a parallel set of validation regular expressions or hashing rules. Construction and generation-ID calculation both pass through the canonical registry. The release payload is governed by a strict JSON Schema Draft 2020-12 contract with bounded fields and `additionalProperties: false`.

## Reachability

`src/resources/architecture_reachability.json` classifies installed Python modules as:

- canonical authority;
- compatibility alias;
- installed support;
- quarantined.

The classification is exhaustive because every installed `src/**/*.py` path is classified by the verifier. Explicit aliases have a maximum line count and an importable canonical target. Explicit quarantine prefixes cover forbidden sender/live packages and the unresolved proof-island modules already named by the production-surface manifest.

## Packaging

The production-surface manifest requires the registry, reachability loader, release identity, and both packaged JSON authorities to exist in every wheel. The focused workflow builds the wheel and independently checks those members.

## Mandatory evidence

`scripts/verify_mpr_4x_01_foundation.py` fails closed when:

- a required schema ID is absent;
- a registered owner module is missing;
- a second `SchemaRegistry` or `canonical_json_bytes` owner appears;
- release identity accepts an unknown or malformed field;
- release hashing bypasses the registry;
- an alias is not thin or its target is not importable;
- any required foundation member is absent from the production surface.

The verifier is part of `scripts/verify_repo.py` and therefore runs in the full repository CI.

## Safety boundary

This foundation does not enable live mode, signer loading, transaction signing, RPC submission, or Jito submission. `production_ready` remains false. Subsequent Mega PRs own runtime composition, protocol/economic execution, and operational release qualification.


## Version evolution compatibility gate

The canonical registry also exposes SchemaRegistry.check_compatibility(...) for an ordered family.vN to family.vN+1 transition. Callers provide reviewed golden fixtures from the previous and/or candidate version and choose BACKWARD, FORWARD or FULL checks:

- BACKWARD: payloads valid under the previous schema must also validate under the candidate schema.
- FORWARD: payloads valid under the candidate schema must also validate under the previous schema.
- FULL: both directions are checked.

The report records schema IDs, mode, fixture counts and explicit findings. Invalid source fixtures fail the report instead of being silently skipped. Metadata-only schemas, cross-family comparisons, non-increasing versions, retired candidates and empty required fixture sets are rejected.

**Evidence limitation:** these are deterministic fixture checks, not a mathematical proof that one JSON Schema is a subset of another. The report explicitly identifies its evidence level as fixture-sampled; production promotion must still review schema diffs, representative archived payloads, migration/replay tests and consumers. This keeps Git + CI as the initial schema-registry deployment without installing a separate Apicurio service or creating a second schema owner.

The existing mpr-4x-01-foundation workflow already watches src/contracts/** and runs tests/architecture/test_mpr_4x_01_foundation.py; the new tests are therefore included in the existing canonical-owner CI gate.
