# CAMPAIGN RPC PROFILES — OPERATOR CHECKLIST (pre-authorization, fill locally)

**Status: TEMPLATE + CHECKLIST ONLY. Nothing here authorizes a capture run.** The profiles file consumed by capture (`--rpc-profiles <file>`) is **operator-supplied and deployment-local**; it is never committed with real endpoints. This template exists so the operator has the exact schema and the exact fail-closed rules.

## 1. Fill steps (operator, local machine only)

1. Copy `CAMPAIGN_RPC_PROFILES_TEMPLATE_V1.json` to a **local, gitignored** path, e.g. `config/external_connections/campaign_rpc_profiles.local.json` (confirm `.gitignore` covers it before filling).
2. For each of the two profiles, replace the `-replace-me` placeholders:
   - `provider` — two **different** RPC vendors (e.g. two separate commercial RPC providers);
   - `operator` — the two vendors must be **independently operated** (two URLs of one operator are NOT quorum);
   - `correlation_group` — two distinct groups;
   - `endpoint` — HTTPS, credential-free URL (no query/fragment/userinfo), reachable `getMultipleAccounts`/`getSlot`/`getVersion`/`getGenesisHash`/`getBlock` read endpoints.
3. If an endpoint requires a key: set `auth_header` to `"Authorization"` (Bearer) or `"x-api-key"`, `credential_ref` to the **env variable NAME only** (e.g. `CAMPAIGN_RPC_A_KEY`), `credential_generation` to a generation label. The value is read from the environment at capture time (`src/qualification_campaign/cli.py`: `MISSING_CREDENTIAL_BINDING:<ref>` if absent). **Never put a key value in any repo file, PR text, log or chat.**
4. Keep `smoke_only: false` — the quorum gate rejects public smoke sources with `BLOCKED_PUBLIC_SMOKE_SOURCE` (the built-in public profile `src/resources/qualification_public_rpc.json` is `smoke_only: true` by design).
5. Keep or tighten quotas (`request_limit=12` / `window_seconds=60` / `campaign_attempt_cap=100` defaults; retries count as physical attempts and the budget does not refill on restart).

## 2. Independence invariants enforced at capture (do not defeat)

- `src/data_plane/rpc.py` `RootedRpcQuorumPolicy`: requires **≥2 distinct providers AND ≥2 distinct operators AND ≥2 distinct correlation_groups** — else `CORRELATED_RPC_SOURCES` / `INSUFFICIENT_INDEPENDENT_EVIDENCE`.
- `max_rpc_slot_delta=2`, `max_root_lag_slots=128`, `max_observation_age_ms=45_000`, identical `payload_hash` at the highest slot, matching `feature_set`, genesis must equal mainnet genesis.
- Missing or invalid profiles file entirely → `BOUNDED_REVIEWED_RPC_PROFILES_REQUIRED` / `INDEPENDENT_ROOTED_RPC_PROFILES_REQUIRED`.
- A single-RPC capture is allowed but the rooted verdict stays `BLOCKED_SINGLE_SOURCE` — do not bypass.

## 3. Offline structural validation (no network)

- ProviderProfile side: construct both profiles via `src/qualification_campaign/profiles.ProviderProfile(**entry)` (validates HTTPS/credential-free endpoint, role, schema_version) — recorded in the preflight receipt on this branch.
- Connections-registry side: `python -m scripts.validate_external_connections docs/roadmap/campaign-start-preflight-2026-11-21/CAMPAIGN_CONNECTIONS_PROFILES_MPR2602_V1.json` (schema `mpr2602.connections.v1`; `enabled:false`, `reviewed:false` until operator review).

## 4. Typed blockers cleared/not cleared by this template

| Blocker | State |
|---|---|
| `BOUNDED_REVIEWED_RPC_PROFILES_REQUIRED` | cleared at capture time once the operator supplies the local filled file |
| `INDEPENDENT_ROOTED_RPC_PROFILES_REQUIRED` / `CORRELATED_RPC_SOURCES` | cleared only when the two filled profiles pass the quorum gate on real reads |
| `LIVE_READ_NOT_AUTHORIZED` | **NOT cleared by this PR** — the operator's explicit authorization of manifest + budget remains a human gate |
| `BLOCKED_SINGLE_SOURCE` | **NOT cleared by this PR** — cleared only by a real two-source quorum capture |
