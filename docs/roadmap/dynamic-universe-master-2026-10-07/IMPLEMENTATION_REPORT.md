# Dynamic Universe implementation and qualification handoff

Assignment: `CODEX_START_HERE.md`, read completely. Implementation starts from PR #576 head `ab529f5fc8a3f1ca00ce767a48a15f304029f808` on `codex/dynamic-universe-master-assignment-2026-10-07`.

## Implemented in assignment order

1. **GPR-01A:** canonical chain/identifier keys; immutable identity generations; HARD_BIND/VERIFY_STARTUP bootstrap assertions; runtime RESOLVE_LIVE workflow; ambiguity, stale data, registry disagreement and chain disagreement receipts. Reuses PR117 bootstrap and all 27 unresolved Part A entries. Changed live identifiers retain historical seeds. Solana mint reader verifies initialized account, program, decimals, authorities, extensions and supply; Sui bridge requires full type, package version and checkpoint via gRPC/Core, with no new JSON-RPC dependency.
2. **GPR-01B:** bounded live Sanctum and DeepBook registry adapters, Jupiter corroboration adapter, normalized venue-reader contract, lifecycle history, complete-snapshot retirement, provenance and underlying liquidity identities. Timeout/partial/truncated snapshots cannot retire a market. Additional venue SDK readers remain integration work.
3. **GPR-02:** direct, venue-fragmentation, direct/synthetic, parity, LST, NAV, stable, wrapper, oracle, cross-chain signal and flash-capital relations. Fresh market evidence is required. Shared resources cannot count as independent venues. Heat inputs and trigger-aware quota/backoff scheduling are separate from execution. Exact 3/4-hop shadow cycles reuse `CircularGraphCandidateDetector`; 3..5-hop topology shortlists reuse `search_bounded_cycles`. Five-hop topology does not acquire a new exact paper contract.
4. **GPR-03:** immutable partitioned Parquet residual observations, deterministic replay, rolling and lagged windows, sample provenance, source-alias penalties and durable anomaly windows. Correlation findings remain DISCOVERY_ONLY. Raw receipts use compressed immutable blobs. Retention settings are recorded; automatic compaction/expiry and long-term aggregates are not implemented.
5. **GPR-04:** separate financing graph, explicit live reader contracts for Project0/Kamino/NAVI/DeepBook/Scallop, exact NAVI unit conversion, provider disagreement invalidation, observed capacity/fees/constraints and PR118 amount grids/cost ledger. Provider SDK bridges must supply normalized current bank/reserve/pool evidence; they are not configured in this environment. No borrow, repay, signer or sender operation exists in this owner.
6. **GPR-05:** durable identity → market → exact observation receipts; replay-backed existing-owner handoff; closed-route paper reconciliation against observed financing and PR118 costs. A missing QPR owner or stop condition denies promotion. A bounded real discovery diagnostic records source failures and unresolved identities; it cannot write QPR PASS.

**TON-RADAR-01**, developed in parallel, provides bounded STON assets/pools/stats polling, optional injected read-only Omniston enrichment, address validation, shared-resource tags, durable journal replay and negative evidence. TON remains DISCOVERY_ONLY / TON_ASYNC_MULTI_CONTRACT. Its live schema could not be confirmed through the current proxy.

## QPR prerequisite and stop condition

The selected branch has no `src/qualification_campaign` owner. Read-only inspection found the existing upstream branches:

- QPR-01 `8baeb41139b5735859933783392d7f4802bc8337`
- QPR-02 `4a89d0e18070529e8f9c9e240a30ed3acb6fad38`
- QPR-03 `476c3782a813323b6bb279fe08cb834bf80035c0`

Their prior handoff records READ_ONLY_REAL_DATA_CAMPAIGN_V1 **PASS**, stronger qualification **BLOCKED**, production promotion false and **stop_before QPR-04**. Those branches were fetched for inspection, not merged. That prior-generation summary is not replayable current-generation authorization. `ExistingQPRReadiness` delegates to the existing `qualification_campaign.cli.report` owner when it is present and retains its handoff unchanged. The promotion boundary respects its qualification verdict and stop condition. No environment variable or discovery response supplies authorization.

The new subsystem is a library and diagnostic CLI, not wired into the application boot path. Signer, sender and submission modules are not imported by the new owners. Existing CLI inspection confirms disabled mode, `live_enabled=false`, `signer_loaded=false`, `sender_loaded=false`.

## Real read-only observations

The first bounded diagnostic captured **245 Sanctum assets**, **21 DeepBook coins** and **24 DeepBook markets**. It loaded **135 bootstrap jobs**, including all **27 RESOLVE_LIVE jobs**. There were **12 historical symbol disagreements** and **2 ticker collisions**. Registry response bytes and hashes, resolution receipts and negative evidence are retained outside Git in `/workspace/dynamic-universe-campaign`.

Jupiter, Solana RPC and STON requests were denied by the HTTPS proxy. The diagnostic returned exit **2 / BLOCKED**, with no canonical identities promoted, no profitable size-band claim and no correlation/financing findings inferred from missing exact state. Git access established that PR #576 and the requested branch had the same head; GitHub API access to PR metadata returned Forbidden.

## Reproduction and validation

Use the existing checkout; each cloud task is already isolated. Do not create a worktree unless requested. Dependencies were installed with CPython **3.13.15** and the unchanged hash-verified `requirements-dev.lock`; the installed repository CLI was validated. Use `/workspace/.venv-studious/bin/python` or activate that environment.

Focused checks cover resolver ambiguity, schema drift, stale and missing evidence, independent-provider disagreement, duplicate markets, Token-2022/Move semantics, dynamic capital changes, deterministic residual replay, QPR stop conditions and the existing graph/sizing/split-flow owners. The full socket-disabled offline suite passed **4,976 tests**, with **1 live test deselected**; no test failed. Black, undefined-name checks, mypy for all 18 new source modules, dependency consistency and the isolated installed-wheel/package smoke passed. CI is defined in `.github/workflows/dynamic-universe-read-only.yml`; it runs offline tests with sockets disabled plus formatting and type checks. Remote CI has not been observed through the denied GitHub API.

To repeat the diagnostic after a meaningful network/configuration change:

```bash
cd /workspace/studious-pancake
source /workspace/.venv-studious/bin/activate
PAPER_TRADING_ONLY=true LIVE_TRADING_ENABLED=false JITO_ENABLED=false \
python -m src.discovery.dynamic_universe.campaign --live \
  --output /workspace/dynamic-universe-next-diagnostic \
  --generation '<reviewed-code-and-config-generation>'
```

This is explicitly a bounded discovery diagnostic. A qualifying campaign must use the generation-bound QPR manifest, governed source dossiers/transport and journal after those prerequisite owners become available. Current exact Sui and lender SDK bridges remain unconfigured. Future venue bindings must reuse `ShadowMarketGraphIngest` rather than treating discovery records as executable edges.
