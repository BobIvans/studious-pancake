# PR-043 key and Jito credential rotation drill

This drill is written for operators. It is intentionally conservative: stop
submission first, rotate credentials second, then re-enable only after redacted
status and readiness checks pass.

## Trigger conditions

Run the drill immediately when any of the following happens:

- wallet private key, seed phrase, keypair bytes, or Phantom export is exposed;
- Jito UUID/auth credential is exposed;
- signer host, CI runner, laptop, or container is suspected compromised;
- dependency audit reports a critical vulnerability in signing, RPC, HTTP, or
  serialization code;
- release rehearsal requires proof that rotation works.

## Wallet signer rotation

1. Set runtime/canary to safe idle or disabled; do not rely on code changes to
   stop trading.
2. Disable the old signer reference in the secret store/keychain/file vault.
3. Generate a new signing key outside the repository and outside plain env.
4. Fund the new wallet only after minimum reserve and rent budget are known.
5. Update `wallet.public_key` and `wallet.signer_reference` to the new reference.
6. Run the config doctor and signer-policy tests.
7. Verify redacted status contains only `env:<redacted>`, `file:<redacted>`, or
   `keychain:<redacted>` references.
8. Revoke/empty the old wallet after accounting for rent, token accounts, and
   any outstanding reservations.
9. Attach the redacted drill result to the release/canary evidence bundle.

## Jito credential rotation

1. Set `providers.jito.enabled=false` or disable bundle submission policy.
2. Revoke the old Jito UUID/auth credential in the credential source.
3. Store the new credential in the secret store/keychain/file vault.
4. Update `providers.jito.auth_reference`; do not paste the UUID into logs or
   config snippets.
5. Run readiness in shadow mode and confirm redacted status hides the locator.
6. Re-enable Jito only after endpoint, auth, and ambiguous-submission tests pass.
7. Record rotation timestamp, operator, old reference label, and new reference
   label without storing credential values.

## Evidence checklist

- Runtime was disabled or safe-idle before rotation.
- No inline key material appeared in config, logs, fixtures, or PR comments.
- New signer/Jito references are structural references, not plaintext values.
- Config fingerprint changed after rotation.
- Readiness/doctor checks passed after rotation.
- Old credential was revoked or emptied.
