# PR-120 — Unified secret resolver, config identity and current Jito auth modes

This patch implements the PR-120 configuration boundary without enabling trading,
senders, signer import, RPC submission, Jito submission, MarginFi execution or
paper/live runtime stages.

## What changed

- Added `src/config/secret_resolver.py` as the single resolver boundary for
  typed secret references.
- `env:` now resolves through a redaction-safe `SecretHandle` instead of ad-hoc
  environment lookups.
- `file:` now resolves only from an absolute, regular, non-symlink, current-user
  owned, restrictive-permission, UTF-8, single-line file.
- `keychain:` now fails explicitly until an OS-specific reviewed adapter is
  introduced; it never silently returns `None`.
- `RuntimeConfig.fingerprint()` now includes the non-secret secret locator
  identity, so `env:KEY_A` and `env:KEY_B` produce different fingerprints while
  `redacted_dict()` still hides locator names.
- `JitoConfig` now models `auth_mode = none | uuid`.
- Jito default/unauthenticated sends are represented by `auth_mode: none`.
- UUID validation is required only when `auth_mode: uuid` is selected.

## Safety properties

- Secret values are not included in `repr()` or `str()` for resolved handles.
- Unsupported schemes fail closed through `SecretResolutionError`.
- `config doctor --check-secrets` exercises the real resolver for every declared
  secret reference.
- A Jito UUID reference cannot be provided unless `auth_mode: uuid` is explicit.
- `auth_mode: uuid` cannot pass without an auth reference and a UUID-shaped value
  during secret checking.

## Verification

Focused tests:

```bash
python -m pytest \
  tests/test_pr026_typed_config.py \
  tests/test_pr026_config_doctor.py \
  tests/test_pr120_secret_resolver_config_jito.py \
  -q
```

Repository verification:

```bash
python scripts/verify_repo.py --skip-dependency-audit
```

## Non-goals

- No credential rotation or history purge; PR-112 owns incident response.
- No provider admission change.
- No live sender or signer enablement.
- No Jito transaction/bundle submission path.
- No MarginFi, paper, canary or soak changes.
