# PR-215 — Typed configuration, trusted time and dependency ownership gate

This slice starts Pass 7 corrective package **PR-215 — Typed Configuration, Trusted Time and Dependency Ownership**.

It is intentionally additive, offline and sender-free. It does not read real secrets, inspect the developer environment, connect to providers, build or submit transactions, start a signer, start a sender, migrate a database or claim production readiness.

## Why this exists

Pass 7 identified that the repository cannot safely complete production work while configuration, clock domains and dependency profiles are ambiguous:

- source reads many environment keys that are not generated from one typed schema;
- the same keys can have conflicting defaults in different files;
- direct `os.environ` and wall-clock calls bypass fingerprint and evidence policy;
- runtime dependency locks can include service/tooling roots;
- direct imports may rely on accidental transitive dependencies.

This gate makes those acceptance requirements explicit in one deterministic report:

```text
pr215.typed-config-time-dependency.v1
```

## Files

- `src/pr215_typed_config_time_dependency.py`
- `tests/test_pr215_typed_config_time_dependency.py`
- `.github/workflows/pr215-typed-config-time-dependency.yml`

## Requirement map

| Requirement | Findings |
|---|---|
| `TYPED_CONFIGURATION_SCHEMA` | F-280, F-281, F-282 |
| `CONFIG_FINGERPRINT_PARITY` | F-280, F-281 |
| `TRUSTED_TIME_BOUNDARY` | F-283 |
| `DEPENDENCY_PROFILE_SEPARATION` | F-284, F-285, F-286 |
| `DEPENDENCY_OWNER_AND_IMPORT_EVIDENCE` | F-287, F-288 |
| `SENDER_FREE_CAPABILITY_BOUNDARY` | F-280…F-288 |

## What the gate requires

### Configuration

- Typed schema generated env reference.
- Runtime observed keys, example keys and quarantined legacy keys are compared.
- Unknown runtime keys and stale example keys must be detected.
- Conflicting defaults fail closed.
- Direct env access is allowed only at approved bootstrap/secret/tooling boundaries.
- Root command and installed command must report the same config fingerprint.

### Trusted time

- Separate duration clock, trusted UTC clock and chain context/slot clock ports.
- Direct wall-clock access in domain/runtime code is rejected.
- Durations must be finite, positive and bounded.
- Wall-clock fault injection and chain slot/height context binding must be evidenced.

### Dependencies

- Runtime, service, analytics and dev lock profiles are separate.
- Exact sync is tested.
- Runtime lock excludes service/analytics/dev roots.
- Optional extras require explicit selection.
- Dependency graph is compared to an allowlist.
- Every direct dependency has owner and import evidence.
- Direct imports must be declared direct dependencies.
- `certifi` direct import requires a direct dependency declaration.
- Unmanaged requirements aliases are absent.

## Safety boundary

The report always returns:

```text
live_capability_allowed = false
signer_capability_allowed = false
sender_capability_allowed = false
```

This PR therefore cannot enable live execution or make sender/signer code reachable.

## What this does not complete

This is not the full PR-215 implementation. Remaining work must wire the contract to generated configuration materialization, replace direct environment and wall clock reads, regenerate exact dependency locks from `pyproject.toml`, and run the checks against the installed wheel/composition root rather than self-declared evidence.

## Focused verification

```bash
python -m compileall -q \
  src/pr215_typed_config_time_dependency.py \
  tests/test_pr215_typed_config_time_dependency.py
PYTHONPATH=. python -m pytest -q tests/test_pr215_typed_config_time_dependency.py
```
