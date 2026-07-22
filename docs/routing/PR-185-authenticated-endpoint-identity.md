# PR-185 authenticated endpoint identity and transport hardening

PR-185 closes the first active transport slice of the endpoint-identity debt
identified in snapshot `(11)`.

## Active changes

`src/routing/transport.py` now:

- rejects URL username/password credentials;
- strips userinfo, query and fragment from safe-display URLs;
- rejects URL fragments and inline query strings by default;
- requires canonical lowercase ASCII/IDNA hostnames;
- allows only explicitly reviewed TCP ports;
- rejects private, loopback, link-local, multicast, reserved and unspecified IP
  literals unless an internal-service policy explicitly permits them;
- creates the default HTTPX client with `trust_env=False`;
- disables redirects;
- constructs an explicit verified `SSLContext`;
- requires TLS 1.2 or newer;
- uses an explicit CA bundle and records its SHA-256 identity;
- optionally fails closed against a reviewed CA bundle digest.

Request query parameters remain supported through the dedicated `params` argument,
so credentials and dynamic request values do not need to be embedded in endpoint
URLs.

## Security result

Ambient `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `SSL_CERT_FILE`,
`SSL_CERT_DIR` and `.netrc` behavior can no longer modify the default active HTTPX
client because environment trust is disabled.

Errors and status output do not retain URL userinfo or query credentials.

## Safety boundaries

This PR does not:

- enable live trading;
- add signer or Jito submission;
- pin public-provider IP addresses;
- claim full DNS-rebinding protection;
- inspect the final connected socket peer;
- introduce internal-service mTLS identities.

A later PR-185 integration slice should add controlled resolver/egress peer
verification and authenticated internal signer/admin channels.

## Verification

```bash
python -m pytest tests/test_pr185_authenticated_endpoint_identity.py -q
python scripts/verify_repo.py
```
