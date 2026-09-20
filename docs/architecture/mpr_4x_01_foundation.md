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
