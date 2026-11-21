# DATA CAPTURE RUNBOOK — READ-ONLY CAPTURE + DETERMINISTIC OFFLINE REPLAY

**Status: `PREPARED_ONLY` — NOT EXECUTED IN THIS PR.**
**Campaign default: `CAPTURE_ONLY`.** This runbook describes the first allowed run (data-only, sender-free, read-only). It sends no transactions, signs nothing, borrows nothing, pays no tips, creates no accounts, activates no provider, spends nothing and starts no live campaign. `CAPTURE_ONLY` evidence is never `PAPER_QUALIFIED`.

Authority documents: `DATA_CAPTURE_TO_PAPER_GATES_RU.md` (states, gates, hard stops), `CAMPAIGN_MANIFEST_CAPTURE_ONLY_V1.json` (this campaign's manifest), `SOURCE_AND_PROVIDER_READINESS_V1.json` (source statuses), `STRATEGY_SOURCE_OWNER_CROSSWALK_V1.json` (owners).

---

## S1 — Campaign states recap

| State | Purpose | Does NOT prove |
|---|---|---|
| `CAPTURE_ONLY` | Broad universe + source-quality evidence via governed read-only discovery, identity resolution, bounded authorized account reads, raw journal, replay | Exact executable depth, profitable route, loan capacity, paper qualification |
| `EXACT_SHADOW_CANDIDATE` | Complete amount-specific direct edges and route economics (PR118 grid, dedup, offline builds) | Lender qualification or paper PASS by itself |
| `PAPER_QUALIFICATION` | Installed canonical sender-free qualification via R06/QPR/campaign authority only | Live trading / signer / production readiness |

The first run requested here is `CAPTURE_ONLY`. It may start before every R02/R03/R05 paper prerequisite is complete, but must report exact blockers and may never claim `PAPER_QUALIFIED`.

## S2 — Gate 0: campaign authority and source preflight (before any read)

1. Pin current main SHA (`release.git_commit` in the manifest), runtime authority generation/hash, policy bundle, source registry and manifest digest. Hashes left `null` stay blocked behind typed blockers in `unbound_hash_blockers` — a null hash is not zero, it is not bound.
2. Validate `CAMPAIGN_START_V1`; require current docs, license/ToS, auth scope, endpoint, schema, limits, rate/physical-attempt budgets, storage cap and rollback.
3. Verify each provider's owner, source/operator identity, correlation group and real independence from every other provider.
4. **No credential probing.** A configured secret reference may be declared by the human/operator only; its value never enters source code, PR text, logs or this pack.
5. Public/shared Solana RPC is exploratory only. A single RPC produces candidate capture, but the rooted verdict stays `BLOCKED_SINGLE_SOURCE`.
6. An independent rooted source set requires **at least two separately operated providers/correlation groups**, same genesis, compatible rooted/finalized commitment, explicit slot/context per response, bounded observed skew and state/account hash comparison. Two URLs/accounts of one operator are **not quorum**.

## S3 — Gate A: read-only universe capture

- Discovery uses the **4 existing adapters only** (owner `src/market/discovery.py`; catalog `src/market/source_catalog.py` + `src/resources/market_source_catalog.json`): `dexscreener`, `geckoterminal`, `raydium_api_v3`, `meteora_dlmm_data` — statuses `EXISTING_DISCOVERY_ADAPTER`. No new source catalog or discovery adapter is added.
- Seed pairs `SOL/USDC`, `USDC/USDT`, `SOL/JitoSOL`, `SOL/mSOL`, `SOL/JupSOL` are **search hints** with semantics `DISCOVERY_HINT_ONLY_EXACT_MINT_RESOLUTION_REQUIRED`. Never hardcode that a pair or pool exists.
- Exact mint resolution uses the canonical **`AssetResolver`** (`src/assets/resolution/resolver.py`): Solana genesis + mint + token program + decimals + relevant extension state; ticker is display-only.
- Rotation policy `score_plus_venue_diversity_plus_source_diversity_plus_negative_controls` with **negative-control fraction 0.2** from the manifest. Do not over-index one popular pair or one discovery provider.
- Capture per candidate: source id/generation/provider/operator/correlation group; request fingerprint; raw response hash; chain genesis, venue/program/deployment id, pool/market address, exact mint ordering; listed fee/tier, pool version/config metadata and source time, clearly flagged **indexed vs rooted**; typed reject decision (admitted-to-identity, discovery-only, unsupported, duplicate/alias, stale, rate-limited, schema drift, missing source, other); quota physical-attempt count, latency, response size, retries/backoff, storage consumption.

## S4 — Gate B: identity and account-read rules

- Identity: exact mint + token program + decimals + Token-2022 extensions; exact venue program/deployment + pool id + token order + vault/reserve/resource identities; alias/wrapper assets are distinct unless a canonical conversion relation proves equivalence.
- Preserve exact raw bytes, account pubkey, owner, discriminator/layout/version, context slot, commitment, endpoint/operator/source generation and SHA-256.
- **`getMultipleAccounts` batches of at most 100 accounts** (RPC contract limit); every response keeps its own context; per-batch context with approved minContextSlot/bounded-skew policy; **never label separately fetched batches as one shared slot**.
- Capture the full dependent-state closure, not just pool/vault balances: CLMM tick arrays + bitmap extension + dynamic fee; DLMM active and directionally reachable BinArrays + bitmap extension + dynamic fee + clock/epoch + token extensions; CPMM config/fee/vaults; orderbook snapshot + deltas + sequence where applicable.
- Incoherent state → store the typed negative reason; the candidate stays unqualified. Helius/Yellowstone/gRPC/shred feeds may trigger a refresh but never replace the full rooted account snapshot required for exact quotes.

## S5 — Quorum / freshness

Every claimed exact/rooted verdict: ≥2 separately operated providers/correlation groups, same genesis, compatible rooted/finalized commitment, explicit slot/context per response, bounded observed skew, state/account hash comparison. Otherwise the verdict is `BLOCKED_SINGLE_SOURCE`.

## S6 — Quotas and budgets

- `external_data_spend_usd_max: 0`; first capture is **no-subscription / operator-approved free-tier only**; `rpc_physical_attempts_max: 0` until an operator-approved bounded profile exists; `storage_bytes_max: 0` until retention is approved.
- Reference budgets recorded in `docs/roadmap/live-data-qualification-2026-11-21/LIVE_DATA_QUALIFICATION_BASELINE.json` on branch `agent/live-data-preflight-2026-11-21` — **`BASELINE_NOT_ON_BRANCH` (typed blocker; that file is not merged to main)**: `quote_input_raw_units=1000000`, `max_radar_reads=4`, `max_quote_reads=4`, `max_native_pools=1` (re-verify before any future capture run; they were a preflight baseline, not this campaign's grant).

## S7 — Deterministic offline replay contract

- Campaign replay: `python -m src.qualification_campaign.cli replay <output>` reads `campaign-manifest.json` + the durable sqlite journal and re-derives results **with zero outbound network calls** (`evidence.replay_network_calls_allowed: false`).
- Radar/DIN replay: `python -m src.solana_parallel_radar.din_discovery --replay <dir> --output <new>` asserts `network_reads == 0` on completion.
- Existing deterministic lane replays usable as offline evidence: `python scripts/r10_offline_replay.py --json` (experiments A–D), `python scripts/r10_1_pre_api_route_replay.py`, and (post-#660) `python scripts/clmm_dlmm_market_trace_replay.py`.
- Determinism invariant: identical inputs produce byte-identical outputs; every replay receipt records command, exit code, output SHA-256 and a run-vs-run diff verdict.
- **All fixture/replay counts are reported separately from live-capture counts**; live capture count is honestly 0 until a separately authorized capture run happens. Percentages always show numerator and denominator; unknowns/unavailable observations stay in their own population.

## S8 — Stopping conditions (hard stops, verbatim from pack §9)

Stop or downgrade to exploratory/BLOCKED on: missing campaign authority; one-source quorum claim; source identity drift; docs/license/ToS drift; stale or mixed state; incomplete tick/bin/book; unsupported Token-2022 extension; unknown fee/cost; capacity disagreement; alias collisions; any quote mismatch; incomplete repayment; stale blockhash or ambiguous earlier attempt; journal corruption; worker heartbeat failure; unbounded queue/storage; non-deterministic replay; or a requested capability outside this campaign's authorization. UNKNOWN cost blocks positive net result and route admission.

## S9 — Forbidden actions (this campaign, this PR)

No send, no sign, no borrow, no account/ATA/position creation, no provider activation, no tip, no spend, no live mode, no production promotion. `live_enabled=false`, `sign_enabled=false`, `send_enabled=false`, `borrowing_enabled=false`, `relay_submission_enabled=false` (all pinned `false` in `CAMPAIGN_MANIFEST_CAPTURE_ONLY_V1.json` `safety` block).
