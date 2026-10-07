# DIN-01 bounded indexed discovery; exact/paper blocked

Review-only dependencies: RCN-00 #579 and DIN-00 #580. Independent Solana branch targets main; do not merge before dependencies or without approval.

`src.solana_parallel_radar.din_discovery` runs at most four source reads, one physical call per reviewed source/operator, through existing SourceDossier, ProviderProfile, SourceIntakePlane, ProviderGovernance, RecoverableStreamJournal, AssetRegistry, CampaignManifest and SolanaResearchAdapter/ResearchEconomicGraph. Existing batch and targeted catalog converters are reused. There is no signer, sender, quote fan-out or competing graph/journal. Source review pins must match bounded actual documentation bytes and TTL. Missing pins produce a named zero-call blocker; payload bounds remain the transport's original 1 MiB.

Actual latest campaign: three physical reads, each HTTP 200. DEX Screener had an empty result; Raydium and Meteora accepted indexed candidates with retained row rejections. 11 candidate receipts and 11 unique pool identities, so no duplicate pool was observed in this small sample. This does not establish universal alias coverage, token-program ownership, exact freshness or executable truth. Earlier two-source diagnostic had four candidates; campaigns have distinct immutable generations.

Current contracts: DEX Screener official token batch reference and Raydium's advertised Swagger init specification were fetched and hashed. Meteora's old `/api-reference/dlmm/overview` returned 404; its official `llms.txt` led to `/api-reference/dlmm/pools/pools.md` and `/developer-guides/dlmm/api-reference/overview.md`. The current overview explicitly documents 30 RPS and the public pools spec states `security: []`; our subcap stays one read/minute and one total. Other published numerical caps were not reverified. GeckoTerminal's old FAQ redirects to `docs.coingecko.com`; that destination was saved in the environment draft but remains blocked by the current proxy, so GeckoTerminal emitted zero data calls.

Compressed public raw/negative event export and summary are committed under `capture/`. Replay validates export hash/size, manifest, event identities, blob hashes, journal head, original candidate dedup and GPR graph identity, with zero network reads. Replaying the compressed bundle passed. Decompressed evidence scan found zero secrets.

Validation: 99 focused tests passed, including real runner fixtures; the final replay fixtures passed (4 tests covering success, 429, schema drift, missing review and tampering). Canonical `scripts/verify_repo.py` passed: 5331 offline tests, 1 deselected, dependency audit, static/format/type/Bandit checks, wheel/console smoke, clean tree. Receipt-only additions do not change tested code.

DIN-01 remains partial: Gecko review unavailable, independent rooted providers and on-chain mint program/decimals proofs missing. Dynamic Universe exact handoff is deliberately blocked; resolver/graph owners are reused rather than fabricating bindings. DIN-03–DIN-07 must respect these gates. Jupiter and 0x keys are missing and securely declared in environment settings. No 24-hour paper, profit, exact quorum or production claim. Signing/sending remain false.

Replay:

```bash
python -m src.solana_parallel_radar.din_discovery --replay docs/roadmap/din01-bounded-solana-2026-10-07/capture --output /tmp/din01-replay-new
```

For a new bounded capture, fetch and review current official docs, write `--docs-pins` with source-id keys and `path`, `url`, `sha256`, UTC `checked_at`, then supply the existing resolved candidate mint identifiers via repeated `--mint`. The clean CampaignManifest factory binds source/config generations and fetched main. Do not reuse an old capture directory or refresh review timestamps without actually checking current contracts.
