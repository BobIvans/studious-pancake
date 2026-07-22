# MEGA-PR O1 — Active management and materialized release evidence

This is the first active vertical slice of MEGA-PR O1. It replaces the container
runtime's active `http.server` listener and unsigned JSON state with the merged
PR-170 authenticated policy and signed generation-fenced runtime truth.

## Active runtime changes

`src/container_runtime.py` now:

- freezes management policy at startup;
- reads an optional bearer token and state key from owner-only files;
- writes MACed `0600` runtime snapshots with atomic replace and fsync;
- starts `ActiveManagementHttpServer` instead of `ThreadingHTTPServer`;
- exposes only topology-minimal loopback liveness without authentication;
- requires bearer authentication for readiness, operator status and metrics;
- uses the PR-174 canonical readiness payload as the only `/ready` authority;
- rejects stale generation, wrong policy, invalid MAC and invalid readiness hash;
- remains safe-idle with live, signing and submission unavailable.

When no persistent state key is configured, the safe-idle process creates an
ephemeral owner-only companion key beside the runtime state file and removes both
on shutdown. Production deployments should configure a separately mounted key;
Docker health continues to use `/health`.

## Materialized evidence producer

The installed command `flashloan-release-evidence` provides:

```text
flashloan-release-evidence produce ...
flashloan-release-evidence verify ...
```

The producer reads the exact wheel/image/SBOM/provenance files, rejects paths
outside the approved root, symlinks and hardlinks, recomputes SHA-256 values and
creates a release digest. It signs the canonical manifest with a dedicated
owner-only Ed25519 release-attestation key.

The verifier independently:

- reopens every materialized artifact;
- recomputes size and SHA-256;
- recomputes the release digest;
- checks the expected PolicyBundle digest and signer public key;
- cryptographically verifies the detached Ed25519 signature.

A trading-wallet key must never be used as the release-attestation key.

## Safety invariants

- live enabled: false;
- sender reachable: false;
- signer/trading key reachable: false;
- fake success permitted: false;
- caller-supplied evidence hashes accepted: false;
- unsigned or stale state can affect readiness: false.

## Remaining O1 work

This slice does not yet complete the full O1 scope. Follow-up integration still
needs digest-pinned base images/actions, a signed offline hash-locked wheelhouse,
minimal core-paper distribution/SBOM, deployment sandbox smoke, real alert
receiver delivery, backup/restore and rollback rehearsal producers, and the
release-bound non-synthetic soak feeding PR-D and canonical readiness.
