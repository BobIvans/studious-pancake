# PR-112 emergency credential incident response

PR-112 is an emergency security slice. It does not change trading, provider
admission, MarginFi, paper stages, sender paths, signer paths, RPC/Jito
submission or live/canary enablement.

## Trigger

The deep-audit roadmap reported credential-shaped literal values in the tracked
LiteLLM configuration and requires treating every value as compromised. The exact
credential values are intentionally not repeated here.

## Repository changes

- Remove the production `litellm_config.yaml` from source control.
- Add `litellm_config.example.yaml` with environment-backed references only.
- Ignore local `litellm_config.yaml` and LiteLLM runtime database files.
- Extend the offline secret scanner so generic `api_key`, token, secret and
  passphrase fields fail closed when they contain literal provider-shaped or
  high-entropy values.
- Ensure scanner findings and test failures never print matched values.
- Add a redacted incident-manifest schema that records operator actions without
  credential values or reversible hashes.
- Add gitleaks-compatible rules for current-tree and full-history scans.

## Mandatory operator actions outside Git

The repository patch cannot revoke external credentials or rewrite already cloned
history by itself. An operator must complete and review the following actions
before release evidence can be considered closed:

1. Revoke or rotate every affected provider credential.
2. Review provider usage, billing and audit logs for unexpected activity.
3. Record each affected provider in a redacted incident manifest.
4. Run a full-history secret scan before and after history cleanup.
5. Use `git-filter-repo` or an equivalent reviewed process to purge historical
   copies of the old production LiteLLM file.
6. Force-push only after coordinating with every maintainer clone/fork.
7. Invalidate old generated archives, release assets and CI caches that contained
   the old file.
8. Recreate any required local production LiteLLM config from secret references,
   not literals.

## Suggested current-tree verification

```bash
python -m pytest tests/test_pr112_credential_incident_response.py -q
python scripts/security_gate.py --repo-root .
gitleaks detect --source . --config .gitleaks.toml --redact
```

## Suggested full-history verification

```bash
gitleaks detect --source . --config .gitleaks.toml --redact --log-opts="--all"
git filter-repo --path litellm_config.yaml --invert-paths
gitleaks detect --source . --config .gitleaks.toml --redact --log-opts="--all"
```

## Incident manifest rule

The manifest may include provider names, credential aliases, locations and
rotation status. It must not include credential values, reversible hashes, raw
request headers, raw environment dumps or unredacted billing/audit payloads.

A passing PR-112 repository check means only that the new tree is safer and the
runbook/schema/tests exist. It is not proof that off-Git provider rotation or
full-history purge has already happened.
