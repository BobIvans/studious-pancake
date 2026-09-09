# MPR-2618 — credential/trust rotation and emergency revocation

## Base and collision discovery

Implementation base: `main@d23f82e20d10345926742352739b1a6ca3f7a859`.

Observed public branches at implementation time:

- `codex/mpr-2612-final-release-gate`
- `codex/mpr-2613-guarded-production-operations`
- no public MPR-2614, MPR-2615, MPR-2616, MPR-2617 or MPR-2618 branch was observed.

MPR-2617 is therefore `RESERVED_UNOBSERVED`, not assumed absent. This PR deliberately avoids taking provider-governance, signer, release-gate, canary, conformance-sentinel, HA/DR leader-election or human-approval ownership.

## Owned residual

This checkpoint owns only the package's reproduced credential/trust fencing gaps:

1. durable revocation fencing for future supported use of an already-issued handle;
2. one durable preferred credential generation with atomic cutover and bounded overlap;
3. durable current trust-registry generation fencing so an old immutable snapshot cannot authorize a new sensitive action.

It reuses PR-183 `CredentialState`, `SecretHandle`, `TrustAnchorRegistry`, `SignedEnvelope`, `TrustUsage` and cryptographic verification rather than replacing them.

## Implemented

`src/security/credential_rotation.py` adds a metadata-only SQLite authority:

- secret values are never stored;
- per-secret preferred version, rotation epoch, revocation epoch and revision;
- version generation, state, backend reference, consumer and usage scope;
- staged validation evidence binding;
- atomic `BEGIN IMMEDIATE` cutover;
- exact replay receipt and semantic-conflict rejection;
- stale expected-current and supersedes mismatch rejection;
- optional bounded old-generation overlap without restoring old preferred status;
- atomic emergency revoke and monotonic revocation epoch;
- per-use `CredentialFence` checks;
- `FencedSecretHandle` which rechecks the durable fence before every reveal;
- durable trust generation pointer and stale-registry denial before invoking existing PR-183 cryptographic verification.

`MPR2618_DEFAULT_ENABLED = False` remains explicit.

## Regression scope

`tests/test_mpr2618_credential_trust_rotation.py` covers the three reproduced preparation gaps plus:

- staged/validated credentials cannot be used;
- idempotent rotation/revocation replay;
- same-ID semantic conflicts;
- supersedes mismatch;
- multi-writer competing cutover;
- bounded overlap expiry;
- bool generation rejection;
- no secret material in receipt/snapshot representations;
- trust usage separation;
- trust revocation epoch anti-regression.

## Deliberate non-duplication / downstream integration

Not implemented here because those are owned elsewhere or were not publicly observable:

- provider request/accounting cutover — consume MPR-2602 owner;
- signer key-generation enforcement — consume MPR-2608 owner;
- canary/live re-arm behavior — consume MPR-2609 owner;
- full economics — consume MPR-2610 owner;
- release qualification — consume MPR-2611/2612 owner;
- continuous conformance sentinel — reserved MPR-2614 scope;
- HA/DR restore/failover fencing — reserved MPR-2616 scope;
- any MPR-2617 credential/incident ownership — `RESERVED_UNOBSERVED` until an actual ref appears.

These integrations must use this generation/revocation contract rather than creating coequal credential authorities.

## Safety / qualification truth

This checkpoint uses metadata and deterministic test secret bytes only. It does not export/load real credentials or private keys, contact providers, sign transactions, submit to Solana/Jito, arm a canary, enable live mode, auto-rearm, auto-scale, or clear an incident latch.

Real KMS/HSM/provider credential rotation, real inbound webhook overlap, conformance-sentinel invalidation, and HA/restore campaigns remain `BLOCKED_EXTERNAL` / `BLOCKED_INTEGRATION` until their accepted owners and environments are available.
