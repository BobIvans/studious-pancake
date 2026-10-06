# GPR-02 — Solana parallel radar and qualification funnel

This isolated stream builds on the published GPR-01 base
`8c59759b491b6318f259138671dccfea25f2752e`. Shared research contracts,
QPR-02/QPR-03, exact graph owners, dependency declarations and lockfiles are
unchanged. No GPR-04+ implementation is included.

`src/solana_parallel_radar` owns bounded Manifest ticker discovery, DEX Screener
mint batches, targeted existing Meteora/Raydium adapters, economic reference
reads, token semantics inspection, structural comparisons and funnel delegation.
The nine exact priority pairs include all requested stable, BTC, JLP and LST
relations. Native SOL and SPL WSOL remain distinct; quote requests use WSOL.

Radar consumes existing SourceIntakePlane and feeds retained Candidate evidence
to the published SolanaResearchAdapter/ResearchEconomicGraph/VerificationQueue.
Heat, execution_class and evidence_state remain independent. Transport relations
retain CROSS_CHAIN_SIGNAL/REBALANCE_ONLY and cannot enter this exact funnel.

Official upstream contracts are pinned by Git SHA and file SHA256 in
`config/qualification/gpr02-solana-contracts.json`. Manifest's upstream SDK
confirms `mfx-stats-mainnet.fly.dev/tickers` and bounded `/orderbook` semantics.
Ticker discovery is implemented; exact Manifest order-book decoder/admission is
not inferred from its index response. Existing Raydium/Meteora discovery owners
remain authoritative. Current official HTTP docs/schema availability remains a
separate observation; stored roadmap/index-owner pins do not prove a live API.

The official 0x Solana API has no wallet-independent GET price endpoint. Its
documented POST `/solana/swap-instructions` returns amount_out,
min_amount_out and route_plan with unsigned instructions. The governed reference
adapter reads economic fields only. Raw unsigned instructions remain inert
evidence: there is no instruction decoding, transaction construction, signer,
submission, fee payer or capital authority. An explicitly configured public taker
and securely bound `ZEROX_API_KEY` are required. Source schema supplies no context
slot, so slot alignment is UNKNOWN. Pinned Solana schema requires 0x-api-key;
it does not require the EVM-specific 0x-version header.

Jupiter authenticated GET `/swap/v1/quote` provides reference, direct-route and
fresh final diagnostic reads. Its official current docs mark Metis V1 unmaintained;
the stream deliberately consumes the documented economic GET rather than a
transaction-building endpoint. `JUPITER_API_KEY` is resolved only at runtime.
All quote identity, amount, route, freshness, source/provider/correlation generation
and raw hashes are retained. Quote comparisons use integer raw units, retain
correlation and slot uncertainty, and grant no execution authority.

`qualify_exact_request` is the configured exact handoff function. It reconstructs
the retained 0x/Jupiter quotes, replays the current VerificationQueue, calls
QPR-02 NativeRootedSnapshotProvider, obtains actual startup receipts from the
unchanged HardBoundIdentityGate, then calls unchanged ingest_solana_exact and
checks the existing ingest owner's retained accepted decision. Nonempty arbitrary
preview/receipt refs do not authorize anything. Full native pool math remains
blocked for Token-2022. Default capture only gathers diagnostic data and emits
blocked funnel work until reviewed exact bindings, identity policies and independent
RPC profiles are provided.

USDG/PYUSD keep Token-2022 program identity. The separate strict mint validator
checks initialized mint/program/decimals, mint/freeze authorities, account type,
padding, unique bounded TLV extensions, reviewed exact extension hashes,
self-mint metadata binding, fee authorities, epoch rollover and ceiling/cap fee
arithmetic. Hooks, confidential transfer, permanent delegate, pause/interest and
unknown extension semantics fail closed. Reviewed StartupIdentityPolicy is reused;
no expected semantics are learned or approved from live bytes. Mint inspection is
explicitly not a full startup HARD_BOUND pool/representation/quorum receipt.

Sanctum's authoritative LST list supplies exact BNSOL/bbSOL/hSOL/dSOL
mint/program/stake-pool refs. Governed same-bank account reads check pool owner,
mint binding, token program, decimals, mint supply and current Clock epoch before
computing an integer structural rate. That research reference does not qualify
redemption fees or independent quorum. When an LST pair is selected, an additional
Sanctum-filtered Jupiter quote is a correlated comparator, not an independent
staking-rate measurement. Current cached JLP AUM is insufficient to label live NAV;
capture always records CURRENT_AUM_SUPPLY_ORACLE_STATE_REVIEW_REQUIRED.
`nav_arithmetic_only` is only arithmetic and explicitly cannot produce a NAV receipt.

Capture/replay use CampaignEvidenceStore, RecoverableStreamJournal,
ProviderGovernance and the unchanged verified campaign transport. Every physical
read has a committed attempt reservation and outcome; auth/transport/schema/rate
failures and missing bindings stay visible. TLS, proxy, checksums and quota policy
remain enforced. Engineering caps are not claimed as provider SLAs or known USD
costs. New campaign directories are mandatory; capture requires a clean commit.

```bash
UV_CACHE_DIR=/workspace/.cache/uv uv venv --python 3.13 .venv
UV_CACHE_DIR=/workspace/.cache/uv uv pip sync --python .venv/bin/python \
  --require-hashes requirements.lock requirements-dev.lock
.venv/bin/python -m src.solana_parallel_radar.cli capture \
  --output /workspace/shared/gpr/gpr02-campaign --pair-index 0
.venv/bin/python -m src.solana_parallel_radar.cli replay \
  --output /workspace/shared/gpr/gpr02-campaign
```

Pair indexes 0..8: USDG/USDC, USD1/USDT, USD1/USDC, xBTC_OKX/cbBTC,
JLP/USDC, BNSOL/WSOL, bbSOL/WSOL, hSOL/WSOL, dSOL/WSOL. Quote size is explicitly
1,000,000 raw input units; absent verified decimals are not guessed as economic size.
Use `--rpc-profiles` for reviewed independent ProviderProfile rows,
`--zero-x-taker` for a configured public address and `--token2022-policy` for
reviewed issuer/representation/extension expectations. Secret values never belong
in these files, Git, saved scripts or chat.

Independent worktree validation: 283 offline tests passed, comprising 64 GPR-02
tests plus GPR-01/QPR-01/QPR-02/QPR-03 and existing shadow aggregation/graph
regressions. Mypy passed for eight new modules; lint, formatting and diff checks
passed. Positive exact funnel proof uses synthetic bytes served through real
governed collectors and independent mock profiles; it is not mainnet qualification.

The bounded real-data campaign and final exact-head receipt are recorded in the
separate GPR-02 handoff. Stop before GPR-04.
