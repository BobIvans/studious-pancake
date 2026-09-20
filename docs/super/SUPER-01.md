# SUPER-01 — baseline, data and point-in-time market truth

SUPER-01 aggregates W2-01, W2-02 and W2-05 from the PR-073–150 plan.

## Canonical reuse

The implementation does not introduce replacement authorities.

- W2-01 baseline and upstream reuse remain owned by
  `src.release_gate.agg01_foundation`.
- Shared source budgets remain backed by the PR-197 quota authority and the
  AGG-02 source-budget wrapper.
- Raw journal, StateFrame, analytical DatasetManifest, market graph, capacity
  and fee surfaces remain owned by `src.agg02`.
- NF-090/NF-095 statistical relation and source ablation remain owned by
  `src.decision.agg10`.

## Residual implementation

This SUPER closure adds only contracts absent from the current main.

### PR-084 replay closure

`DatasetReplayReader` verifies the existing DatasetManifest checksum and
optional schema identity before reading a Parquet projection. An as-known replay
cutoff requires integer `available_at_ms`; rows after the cutoff cannot leak
into the selected replay.

### PR-077 transaction-format reads

`src.agg02.transaction_formats` adds a fail-closed capability report,
explicit decoder registry, normalized resource evidence and durable gap
contract. It deliberately does not implement or pretend to qualify a Solana v1
codec. A provider/SDK pair must explicitly attest the format and supply a
reviewed decoder. Missing support is `PROVIDER_VERSION_UNSUPPORTED` or
`SDK_CODEC_UNAVAILABLE`, and failed coverage cannot silently advance a
checkpoint.

### PR-075 point-in-time market universe

`src.agg02.historical_membership` adds NF-337..NF-340:

- append-only lifecycle facts with separate effective and observed times;
- deterministic membership intervals and dataset revisions;
- as-known universe manifests that reject future knowledge;
- explicit migration identity and unknown states;
- exact-denominator survivorship audits that retain later closure/migration.

A later observation with an earlier effective time creates a later knowledge
revision; it does not rewrite an already materialized historical manifest.

## Verification

`scripts/verify_super01.py` maps 11 child scopes and 88 unique primary NF to
their canonical owner symbols. It is invoked by `scripts/verify_repo.py`.

Implementation acceptance and operational qualification are separate. The
verifier keeps the following operational blockers after a successful code
merge:

- `SUPER01_EXTERNAL_COLLECTOR_FLEET_NOT_QUALIFIED`
- `SUPER01_V1_PROVIDER_SDK_CODEC_NOT_QUALIFIED`
- `SUPER01_HISTORICAL_MEMBERSHIP_SOURCE_NOT_QUALIFIED`

## Safety boundary

SUPER-01 is sender-free and effect-free. It does not load private keys, sign
transactions, submit transactions, create remote provider resources, fund a
wallet, enable live trading, or grant production readiness.

## Rollback

Revert the SUPER-01 merge for new research/replay behavior. Existing AGG-01 and
AGG-02 durable authorities remain intact. Historical manifests already emitted
for research must be retained by evidence storage rather than rewritten.
