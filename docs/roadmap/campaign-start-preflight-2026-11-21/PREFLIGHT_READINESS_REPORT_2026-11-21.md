# CAMPAIGN-START PREFLIGHT READINESS REPORT — PR-B (2026-11-21)

**Verdict: `READY_FOR_OPERATOR_REVIEW_NOT_AUTHORIZED`.** The campaign-start prerequisites are prepared offline and bound to exact repo artifacts; nothing was captured, nothing was activated, and every human gate remains explicit. Merging this PR does not start any campaign.

**Base:** `0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54` (main, after merges of #664 and #668). **Head:** filled at commit time. **Scope:** 9 new files under `docs/roadmap/campaign-start-preflight-2026-11-21/` only — docs/config templates; no `src/`, `config/`, `tests/`, `scripts/` changes; no credentials (only env-var names); no network reads beyond official-docs freshness rechecks (AGENTS.md rule 4).

## Deliverables

1. `CAMPAIGN_RPC_PROFILES_TEMPLATE_V1.json` — exactly 2 `prequal.provider-profile.v1` profiles with pairwise-distinct provider/operator/correlation_group placeholders and `.invalid` endpoints; offline receipt: `ProviderProfile(**entry)` construction passed for both, `generation` computed (`a33b30bd…` / `857e333b…`), independence invariant asserted (`PROFILE_INDEPENDENCE_OK`).
2. `CAMPAIGN_RPC_PROFILES_OPERATOR_CHECKLIST.md` — local fill procedure, quorum invariants (≥2 provider+operator+correlation_group; `BLOCKED_PUBLIC_SMOKE_SOURCE`; two URLs of one operator are not quorum), typed blockers table.
3. `CAMPAIGN_CONNECTIONS_PROFILES_MPR2602_V1.json` — companion registry (`mpr2602.connections.v1`, both `enabled:false`/`reviewed:false`, sender-free read-only rpc_methods). Receipt: `python -m scripts.validate_external_connections` → `{"valid": true, "network_effects": 0, "secrets_loaded": 0, "profile_sha256": "7510fd9b…"}`. (Two iterations: `getBlock`/`getVersion` are outside the registry enum for connection profiles — replaced with `getBlockHeight`; note `ProviderProfile` READ_RPC_METHODS differs from the connections-registry enum — recorded here as a nuance, not a defect.)
4. `CAMPAIGN_POLICY_BUNDLE_MANIFEST_V1.json` — 5 components with raw-bytes sha256 (DIN-00 admission ledger, GPR-02 contract pins, representative sources, rooted runtime truth policy, retention policy) + hash-convention definitions.
5. `CAMPAIGN_MANIFEST_CAPTURE_ONLY_V2.json` — binding on top of the merged #664 manifest: `runtime_authority_sha256 = abafb600…` (canonical-JSON digest of `src/resources/runtime_authority.json`; cross-checked against the prequal handoff precedent), `source_registry_sha256 = 16837d79…` (canonical digest of `market_source_catalog.json`; matches runtime-authority generation_bindings), `policy_bundle_sha256 = 89fddcd0…`; self-hash stays null (`campaign_id = digest(manifest)` at capture); whitelist-diff receipt vs V1 (`V2_WHITELIST_DIFF_OK`, no unintended changes); budgets bound as PROPOSED (200 physical attempts, 100 MiB storage, 12/60s/100 per profile, 24h window) with `operator_approval` all-null; status `NOT_AUTHORIZED_NOT_STARTED`; all safety flags false. Runtime-shape receipt: strict `CampaignManifest` dataclass constructed with the bound values — `campaign_id = d92cfcd7…` for this configuration, `digest(to_dict()) == campaign_id: True`, 4-key all-false safety block verified (`RUNTIME_MANIFEST_CONSTRUCTED`).
6. `CAMPAIGN_START_PREFLIGHT_CS01_CS10_V1.md` — CS-01..CS-10 gate mapping with per-item state/evidence/owner/typed-blocker; CS-06 marked `REQUIRES_REAL_CAPTURE_HUMAN_GATED`.
7. `SOURCE_RECHECK_MATRIX_V1.json` — all 25 sources re-checked 2026-11-21: 12 fresh web verifications, **3 dead docs domains (titan_solana, astralane_iris, 0slot — DNS ENOTFOUND)**, 1 redirect drift (geckoterminal → docs.coingecko.com), 1 rate-limited (solana.com 429), openocean drift confirmed and enriched (EVM v4; amount/gasPrice → amountDecimals/gasPriceDecimals), jito/helius sender values re-confirmed (min tips unchanged: 0.001 / 0.000005 SOL; jito min tip 1000 lamports, bundle max 5). No status promoted; aggregator comparator-only rule unchanged (no double counting).
8. `REMAINING_BLOCKERS_TO_FIRST_CAPTURE_V1.md` — every #664 blocker dispositioned: RESOLVED (BASELINE_NOT_ON_BRANCH via #668; hash binding via this PR) / OPERATOR_REQUIRED (profiles fill, quota/retention sign-off, live-read authorization, manifest sign-off) / DAG_NODE_OWNED (N01, N05–N12, PR #655) / CREDENTIALS_REQUIRED (JUPITER_API_KEY, ZEROX_API_KEY — names only; needed for aggregator phase, not the first capture) / ENV_DEBT (3 typed Windows tasks, receipts in #670).
9. This report.

## Safety invariants (grep-verified across all new files)

No signing, sending, borrowing, account creation, provider activation, credential values, tips or spend anywhere. `CAMPAIGN_CONNECTIONS_*` entries are `enabled:false, reviewed:false`; endpoints are `.invalid` placeholders; env references are names only. Statuses never promoted without offline-contract proof; `LIVE_READ_NOT_AUTHORIZED` and `BLOCKED_SINGLE_SOURCE` remain in force.

## Blockers summary

See `REMAINING_BLOCKERS_TO_FIRST_CAPTURE_V1.md` §"EXACT REMAINING LIST": the first read-only capture is gated ONLY on operator actions (steps 1–3) + a real quorum pass (step 4); aggregator phases additionally need credentials (step 5); all other blockers run in parallel through DAG N01–N12.

**Draft until human review. This PR prepares; it does not authorize, execute, or start anything.**
