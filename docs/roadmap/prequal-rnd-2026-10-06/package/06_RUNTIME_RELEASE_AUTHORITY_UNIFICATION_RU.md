# Runtime / Release Authority Unification

## Problem
`src/runtime_authority.py` читает `src/resources/runtime_authority.json`, а `scripts/qualify_release.py` включает digest `config/runtime_authority_map.json` / mirror. Это две разные truth surfaces.

## Target
Один immutable `RuntimeAuthorityManifest`:

```text
runtime_authority_manifest.json
  schema_version
  release_generation
  active_composition_root
  lifecycle_authority
  capital_authority
  provider_authority
  persistence_authority
  capability_manifest_sha256
  source_registry_generation
  policy_bundle_sha256
```

Его digest обязан быть одинаковым в:
- runtime bootstrap;
- qualification campaign manifest;
- release bundle;
- soak evidence;
- final report.

## Remove from runtime identity
- GitHub PR queue;
- branch names;
- roadmap bookkeeping;
- superseded development metadata.

## Tests
- mutate one byte → runtime and release both reject;
- config/runtime mirror mismatch → reject;
- PR queue changes → runtime digest unchanged because queue lives outside manifest;
- installed wheel reads same packaged bytes used by qualifier.
