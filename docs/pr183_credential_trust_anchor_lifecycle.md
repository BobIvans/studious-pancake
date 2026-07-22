# PR-183 — credential lifecycle, trust anchors and secure secret delivery

This PR starts the active PR-183 workstream by replacing the runtime file-secret
read boundary and adding cryptographic trust-anchor verification.

## Active changes

- File secrets use one file descriptor: `os.open` with `O_NOFOLLOW` where
  supported, `fstat`, bounded read from the same descriptor, and no path reopen.
- Secret handles carry a versioned, scoped, expiring `SecretLease` and support
  explicit revocation plus best-effort in-process zeroization.
- Production secret policy denies environment-backed values by default.
- Credential metadata has a staged rotation/revocation state machine.
- `TrustAnchorRegistry` verifies domain-separated signed envelopes using current,
  non-revoked Ed25519 public-key anchors.
- SHA-256-shaped strings are explicitly rejected as signatures.

## Safety boundaries

- No private key is added to the repository.
- No signing service or live sender is enabled.
- No provider credential is fetched by CI.
- No secret value appears in repr, status, evidence, or exception text.
- Existing development resolution remains backward compatible; production callers
  must explicitly use `SecretResolutionPolicy.production_default(...)`.

## Remaining PR-183 work

Follow-up integration should make the production runtime factory always supply a
production policy, persist credential lifecycle state durably, connect signed
release/evidence/operator objects to the trust registry, add managed secret/KMS
backends, and rehearse real provider/signer/evidence-key rotation.
