# PR-199 — Authenticated inbound gateway and trusted webhook identity

## Production contract

PR-199 keeps the PR-188 bounded/durable delivery implementation and places one
reviewed identity boundary in front of it:

```text
Helius configured authHeader
  -> TLS-only trusted gateway / reverse proxy
  -> trusted immediate-peer and proxy-chain resolution
  -> source network policy
  -> server-side webhook/config generation
  -> active logical credential version
  -> PR-188 bounded parsing, canonical dedup and durable enqueue
  -> durable PR-199 inbound request context before HTTP 200
```

Helius `authHeader` is a shared bearer value. It is **not** described as a body
signature or cryptographic proof that Helius produced the payload. Production
acceptance therefore requires the surrounding gateway, network and server-side
configuration evidence as well.

The machine-readable contract is `config/ingress_contract.json`. Public ingress
remains disabled until deployment supplies the reviewed trusted proxy CIDRs,
source CIDRs, gateway identity, TLS termination and an active configuration
generation.

## Server-owned webhook identity

`HeliusDeliveryPlane.accept_delivery()` retains the compatibility
`webhook_id` argument, but the argument is observational only. A value different
from `HeliusDeliveryConfig.webhook_id` is rejected with
`WEBHOOK_ID_MISMATCH`; accepted events always use the server-owned configured
identity.

This closes the reproduced case where possession of one static token allowed
`attacker-wh` and `other-wh` to create separate durable authority domains.

## Trusted proxy semantics

Forwarded metadata is used only when the immediate socket peer belongs to a
configured trusted proxy CIDR. Otherwise:

- `Forwarded`, `X-Forwarded-For` and `X-Forwarded-Proto` are ignored;
- the socket peer remains the client identity;
- direct access is rejected unless the reviewed policy explicitly permits it.

When both `Forwarded` and `X-Forwarded-For` are present, their normalized chains
must agree. Proxy chains are bounded and resolved from the trusted right-hand
side, so caller-prepended addresses cannot select a rate-limit or allowlist
identity.

## TLS and gateway identity

Production policy requires effective TLS. TLS may be verified on the direct
connection or asserted by an approved immediate proxy. An untrusted
`X-Forwarded-Proto: https` value has no effect. The deployment must fail startup
when its TLS/gateway configuration cannot be loaded; plaintext fallback is
prohibited by the production ingress contract.

Optional `required_peer_identities` bind the connection to an mTLS identity,
workload identity or another identity produced by the trusted gateway adapter.

## Credential rotation and revocation

Credentials have logical IDs, versions and lifecycle states:

```text
staged -> active/overlap -> revoked
```

`active` and `overlap` values may authenticate. `staged`, expired and not-yet
valid values fail closed. A replaced policy takes effect atomically for new
requests, so a revoked version fails immediately.

Durable records store `credential_id` and `credential_version`, never the raw
secret or a deterministic `SHA256(secret)[:N]` fingerprint.

## Durable request context

Before returning HTTP 200, the boundary persists:

- immediate peer and resolved client;
- trusted proxy chain;
- TLS and peer identity;
- server-owned webhook ID and config generation;
- logical credential ID/version;
- network and webhook type;
- raw body SHA-256;
- provider delivery metadata;
- monotonic/UTC receive times;
- an explicit `provider_origin_cryptographically_proven=false` fact.

A provider delivery ID cannot later be rebound to a different body digest.
Failure to persist the context converts an otherwise successful delivery into a
retryable 503, preventing a false acknowledgement without ingress evidence.

## Legacy quarantine

The supported PR-199 production contract does not activate either legacy
boundary:

- `src/ingest/helius_webhook_handler.py` — conflicting body-HMAC model,
  untrusted forwarded headers and TLS downgrade behavior;
- `src/webhook_ingest_pr135.py` — standalone model with deterministic secret
  fingerprinting.

They remain historical/quarantined code and must not be wired into a public
listener. The package-level installer ensures both package imports and direct
`src.providers.helius.delivery` imports receive the same PR-199 delivery class.

## Verification

Focused tests cover:

- arbitrary webhook ID rejection;
- static token without gateway context;
- trusted and untrusted forwarded metadata;
- direct gateway bypass;
- TLS and configuration-generation mismatch;
- overlap rotation and immediate revocation;
- durable secret-safe request context;
- provider delivery ID/body conflict;
- compatibility with PR-188 callers that do not yet activate production ingress.
