# GPR-01 — implementation and parallel handoff

GPR V2.2 additive identity/transport delta is reconciled with the completed V2.1
implementation. This change implements only GPR-01 above the
QPR-01/#568, QPR-02/#569 and QPR-03/#570 foundation on continuation branch #571.
GPR-02 and GPR-03 may now develop against the contracts below independently.

`src/research_economic_graph` owns research identity, classification and bounded
verification work. The QPR sources, campaign/journal/governance owners,
MarketObservationV2, ShadowMarketGraphIngest, UniversalArbitrageGraph, multihop,
PR118, split-flow and RouteGraph owners are unchanged.

## Corpus and contracts

- `AssetRegistry` loads the supplied 92 rows without guessed decimals, issuer or
  bridge metadata. Its canonical configuration and digest are order-independent.
  `asset_id` is chain-qualified; exact lookup uses chain + canonical identifier.
  The full representation, token program/Move type and generation remain attached.
  Every legacy alias is chain-scoped and collision-checked, including normalized
  Move address spelling. Native SOL and SPL WSOL remain distinct.
- `CampaignSeed` loads all 14 initial families and 9 DeepBook pool refs from the
  V2.2 family file (including sSUI in F12) and unchanged V2.1 DeepBook file.
  Pool IDs preserve their supplied spelling and also
  expose a normalized 32-byte object ID. They carry IDENTIFIER_VERIFIED evidence,
  with runtime/exact-graph flags false. No broad-universe polling is introduced.
- `ResearchRelation` independently carries heat, execution_class, evidence_state,
  anchors, exact representation refs, venue/pool refs, synthetic paths, provenance,
  observation/availability/source time, source slot, correlation and staleness.
  Changing heat never grants evidence or execution authority.
- `ResearchEconomicGraph` deterministically merges indexed aliases and every
  provenance path. `SolanaResearchAdapter.ingest(evidence)` consumes retained
  QPR-03 Candidates and raw envelopes, including negative observations and attempt
  refs. It validates journal/blob hashes, campaign/source generations and raw
  candidate provenance. Unknown representations remain recorded rejections.
  QPR-03's Solana pubkey/domain contract is unchanged.
- `CandidateScore` decomposes bounded integer scheduling inputs and penalties.
  It makes no profitability claim. `VerificationQueue.build` applies top-K and
  per-chain budgets; `persist` retains scores, computed requests and replay time.
  `replay` verifies identical score decomposition and deterministic work order.

JLP retains a NAV anchor; XAUM retains an XAU oracle reference and tokenization,
redemption and liquidity frictions. PYUSD/USDG initially has only its explicit
USDC synthetic path. Discovering a direct market adds a separate relation.

## Campaign binding and replay

Use the existing clean-checkout QPR-01 factory for actual campaigns. Add these
configuration entries alongside the existing reviewed configuration and source
profiles; do not bypass its repository/authority/source-generation checks:

```python
registry = AssetRegistry.load(pack / "ASSET_REGISTRY_V2.json")
seed = CampaignSeed.load(registry, pack)
configuration["gpr.registry"] = registry.configuration
configuration["gpr.seed"] = seed.configuration
# policy is an explicitly reviewed StartupIdentityPolicy, not inferred metadata.
configuration["gpr.identity_policy"] = dataclasses.asdict(policy)
manifest = CampaignManifest.create(
    repository_root, main_sha=reviewed_main_sha,
    configuration=configuration, sources=reviewed_source_configs,
)
```

The resulting configuration digests must equal `registry.generation`,
`seed.generation` and `policy.generation`. Use a new output directory for a new
campaign generation. Existing QPR evidence lacking these pins cannot be silently
relabeled as a GPR campaign.

```python
graph = ResearchEconomicGraph(registry, seed)
SolanaResearchAdapter(graph).ingest(evidence)
graph.persist(evidence, observed_at_ns=now_ns)
queue = VerificationQueue(graph, evidence)
queue_ref = queue.persist(scores, top_k=14, per_chain_budget=budgets, now_ns=now_ns)

restored = ResearchEconomicGraph.replay(evidence, registry, seed)
requests = VerificationQueue(restored, evidence).replay(queue_ref)
```

These operations use CampaignEvidenceStore/RecoverableStreamJournal and retained
bytes only. There is no additional database or network read during replay.

## Startup HARD_BOUND and exact shadow handoff

`StartupIdentityPolicy` pins explicitly reviewed expected decimals, the complete
representation digest, representation provenance, relevant extensions and current
deprecation/replacement status. Missing policy, missing representation proof,
REVALIDATE/UNRESOLVED and metadata mismatch fail closed.

Create `HardBoundIdentityGate` at campaign startup with the campaign start time
and wall clock. Collect direct state through the existing governed QPR-02 path.
`startup_receipts(relation, verification_id=..., pool_id=...)` then:

1. Replays retained QPR-02 quorum evidence with the canonical policy. Single,
   public-smoke, correlated, disagreeing and failed providers cannot qualify.
2. Checks raw capture hashes, pinned provider generations, freshness after
   campaign startup, finalized slot, actual mint owner/program, decimals, token
   standard/extensions, exact pool program/identity and decoded state agreement.
3. Checks the reviewed full representation/origin/bridge/issuer mapping and
   current identity status. It persists one machine-readable receipt per asset,
   bound to campaign ID, repository SHA, registry/policy generation, state hash,
   pool, slot and raw verification/capture refs.

Receipts are necessary identity evidence, not executable quotes. Exact handoff
replays and reconstructs them again; supplying a flag or rehashing altered receipt
fields cannot authorize use. Missing/old/future/different-campaign receipts fail.

`ingest_solana_exact` accepts a current VerificationRequest, explicit existing
ShadowMarketBinding, retained QPR-02 verification and complete receipt refs.
It obtains MarketObservationV2 from QualifiedRaydiumCpmmAdapter's integer math
and passes it to ShadowMarketGraphIngest. Native decoder/binary generations are
retained with campaign/identity pins. The existing ingest and UniversalArbitrageGraph
continue owning exact graph admission. Research relations do not self-promote.

The positive integration test uses synthetic account bytes served through the
real governed collectors and two independent mock RPC profiles. This demonstrates
the contract; it is not mainnet qualification.

## Parallel follow-up boundaries

**GPR-02 Solana:** consume SOLANA_QPR02_DIRECT_STATE requests. Add the documented
bounded radar/quote integrations and reviewed first-campaign identity policies.
The current QPR-02 native CPMM decoder supports SPL only. USDG/PYUSD retain their
Token-2022 program identity and remain blocked from HARD_BOUND/exact use until a
governed direct-state owner qualifies their extension/authority/fee semantics.
No ticker normalization or environment flag may waive that requirement.

**GPR-03 Sui:** consume SUI_GOVERNED_CHECKPOINT_OBJECT requests, exact Move identity
refs and the 9 research-only DeepBook pool refs. Supply a separate governed
checkpoint/object/version, coin-type, depth and fee verification path. GPR-01
does not admit Sui into the Solana receipt/exact graph boundary. No legacy Sui
JSON-RPC integration or PTB signer/executor was added.

F14 and bridge/CCTP/Wormhole relations remain CROSS_CHAIN_RESEARCH or
REBALANCE_RESEARCH work. Even HOT signals and revalidated identities never create
atomic transport edges. The broader symbolic universe remains inactive until
measured evidence produces bounded research work.

## Verification commands

From `/workspace/studious-pancake`, activate the prepared Python 3.13 environment:

```bash
source .venv/bin/activate
python -m src.research_economic_graph --pack docs/roadmap/gpr-parallel-radar-rnd-2026-10-06
python -m pytest -q --disable-socket --allow-unix-socket \
  tests/test_gpr01_research_economic_graph.py \
  tests/test_qpr01_campaign_identity.py tests/test_qpr02_data_plane.py \
  tests/test_qpr03_source_intake.py tests/test_shadow_market_data_aggregation.py \
  tests/test_shadow_arbitrage_graph.py
python -m mypy --config-file mypy.ini --follow-imports=silent src/research_economic_graph
python -m black --check src/research_economic_graph tests/test_gpr01_research_economic_graph.py
python -m flake8 src/research_economic_graph tests/test_gpr01_research_economic_graph.py --select=E9,F63,F7,F82
```

The installed package also exposes `python -m src.research_economic_graph`; pass
the absolute path to the original roadmap corpus when outside the checkout.
The original research JSON files remain the source of truth and are not copied
  into a second registry. A scoped CI workflow runs these same offline checks.

Publication reconciliation validation: **226 offline tests passed**, including
the affected V2.2 identity/transport tests and existing QPR-01/QPR-02/QPR-03 and
shadow exact graph regressions. Mypy passed for all eight research modules;
formatting and lint passed. No existing QPR or exact-owner source was changed.
The remote starting point was `ad1cf6be8faf32e91bd935316aebe259270c8375`.
The publication receipt records the resulting clean commit and independently
checked remote PR head outside the checkout to avoid a self-referential SHA.

V2.2 also loads four `TransportTransformation` definitions. Three concrete
research/rebalance relations refer to existing representations; the Wormhole
template creates no edge. USDT0 Legacy Mesh uses native Solana USDT, CCTP uses
native USDC endpoints, and Wormhole targets retain their exact wrapped identity.
Transport IDs and aliases are rejected as fake token identities. All transport
edges remain non-atomic; their corpus is pinned in the seed generation and replay.

This commit is the shared GPR-01 base for separately authorized GPR-02/GPR-03
worktrees. No signer, sender, transaction submission, live capital, automatic
production promotion or GPR-04+ implementation is included.
