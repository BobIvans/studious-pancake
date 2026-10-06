# QPR-03 — campaign-start source intake

Implemented only the campaign-start slice. QPR-04 through QPR-10 remain unexecuted.

SRC-001: SourceDossier + ProviderProfile + DiscoveryAdapter + SourceIntakePlane use the existing MarketSourceCatalog, ProviderGovernance and RecoverableStreamJournal. A new source fills one existing FREE-SOURCE slot, supplies one adapter factory and one dossier/config entry. Catalog admission remains owned by MarketSourceCatalog. Dossier and provider generations, request/response schema identity, auth references, period-quota metadata, terms/license metadata and renewal TTL are machine-readable.

SRC-002: checked-at + official document content hash + TTL + request/response contract identity are pinned to campaign generation. Stale/future dossiers and schema/request/profile mismatches block before I/O. The checked official API pages are in `config/qualification/representative-sources.json`; old planning URLs are preserved as historical input.

LIC-001: license/commercial-use/redistribution status is explicit UNKNOWN/UNREVIEWED when not established. Indexed sources only produce DISCOVERY_ONLY candidates. This phase grants no redistribution, execution or promotion authority.

NET-001/ENV-001: selected sources use the canonical governed transport; credentials resolve only in CLI/bootstrap and never enter dossiers or saved scripts. The source request builder cannot record auth headers. Reflected credential values are redacted in retained payloads with original/retained hashes distinguished. Retry is explicit, quota-owned and journaled.

Each raw envelope retains source/profile/operator/correlation generation, request fingerprint, raw response/hash, observation/availability times, supplied source time/slot/root/sequence when available, HTTP/schema/empty/timeout/cancellation failures and negative quality. Source-supplied context does not grant exact authority. Candidate identity excludes indexed venue aliases; deterministic dedup retains every provenance path. On-chain linkage requires retained candidate provenance, canonical quorum replay verification and exact pool/mint identity. Even ROOTED_REFERENCE is not an executable quote or strategy verdict.

Built-in proof set: DEX Screener, GeckoTerminal and Raydium indexed discovery via existing request builders/decoders. No broader integration inventory was completed. All 64 original blank planning slots remain unchanged. `intake-template` produces a machine-readable runtime skeleton alongside the selected original planning slot.

CLI: `python -m src.qualification_campaign.cli capture`, `replay`, `intake-template`. Capture requires a clean checkout and binds exact current repository/main SHA, canonical runtime authority, configuration and source generations. New output directories are required for different identities. Replay verifies retained event/blob hashes and performs no network requests. Existing native qualification CLI also consumes the canonical campaign identity.

Validation before real run: 154 focused/regression tests passed. Full isolated wheel/package smoke passed after installing CPython 3.13.5 with ensurepip; the host interpreter lacked ensurepip. No signer/sender/submission modules are admitted into the campaign composition. Real bounded run evidence and exact commit receipts are recorded separately in the final handoff.
