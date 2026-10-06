# QPR-02 — qualification data plane

DATA-001/DATA-002: native reads now use ProviderProfile. Public RPC lives in a packaged smoke-only profile, not collector/decoder URL literals. Reviewed HTTPS profiles accept header authentication by reference and carry provider/operator/correlation, generation, endpoint/docs, window quota and a persistent campaign attempt cap. Credential-bearing query URLs are rejected.

SLOT-001: `GovernedNativeCpmmCollector(snapshot_provider=...)` consumes `NativeRootedSnapshotProvider`. It runs the existing native decoder per provider and the canonical RootedRpcQuorumGate with actual genesis, node version/features, processed/finalized slots, exact account bytes and block identity. Same context slots are required. Every configured failure remains visible; disagreeing/correlated/smoke/single sources cannot qualify. Even a rooted quorum is only data evidence; deployment, costs, holdout and continuous-capture gates still block the strategy verdict.

RATE-001/OBS-001: CampaignEvidenceStore wraps the existing RecoverableStreamJournal; ProviderGovernance retains window spend in UnifiedLifecycleAuthority. Attempt claims commit before I/O, survive restart and use an interprocess lock for the campaign cap. Automatic retry is disabled in campaign transport; explicit retry consumes a new reservation and observation. Raw replies, 429/Retry-After, auth/schema/transport failure, cancellation and quorum inputs/decisions are retained. Large capture bodies are individual evidence records; bundles reference them. Replay performs no networking.

Native `collect_report` creates a clean exact-SHA CampaignManifest, uses its identity for persistence/config binding and returns identity in the report. Captures and replay carry campaign/quorum identity. Existing synthetic fixtures remain explicitly synthetic and blocked.

Minimal architectural blocker fixed separately: canonical governed sender-free allowlist lacked read-only `getVersion`, so node identity probes could not execute. Only that read method was added.

Validation: 81 focused/regression tests passed, including real collector → governed mock transport → rooted gate → durable restart. Production promotion remains unavailable. Long-running producer and deployment/cost closure are deferred as requested.

## Real-data blocker discovered during this phase

A real `getGenesisHash` reply exposed a truncated registry/model/default cluster pin (the CAIP-style prefix had been used as a full RPC hash). The active registry/default/native CPMM pin and explicitly synthetic vector now use the full 32-byte RPC hash `5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d`. The corrected chain registry is pinned in runtime authority. Historical real evidence is not rewritten and must be recollected under this generation. This is the minimum fix needed for native collection, not a broad legacy migration.
