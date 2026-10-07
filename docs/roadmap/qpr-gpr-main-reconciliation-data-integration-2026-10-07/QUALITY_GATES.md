# QUALITY_GATES — evidence and negative tests before claim of success

## Gate 0: release / remote truth

- GitHub PR base **exactly `main`**; remote head SHA exists and intended files/tests can be fetched at it.
- GitHub merged flag is checked *together* with base and the current `main` tree. Local commits, PR titles and issue comments do not count as merges.
- RCN-00 both generations present: `qualification_campaign`, `research_economic_graph`, `solana_parallel_radar`, `gpr_sui_shadow`, dynamic-universe, relation-generators, correlation-ledger, flash-capital-graph.
- All six overlapping paths have explicit before/after semantic notes, tested exact function or import, and fresh pinned lock.
- Run canonical root/workflow commands and hash-locked dependency bootstrap. Never relax safety gates, dependency hashes or workflow check names.

## Gate 1: source admission (DIN-00..02)

| Test case | Expected |
| --- | --- |
| No key / invalid reference / wrong host | typed BLOCKED before wire |
| Two API keys, same operator | one shared operator budget; **not** independent quorum |
| 429 + Retry-After | bounded retry; no uncontrolled retry fan-out |
| 401/403 credential failure | authentication reason retained; no secret printed |
| HTTP 200 invalid JSON / unexpected schema | raw hash + negative schema-drift, no candidate |
| gzip/deflate response | accepted only under explicit transport caps and schema |
| 10 MB payload over narrower per-source bound | fail closed; no cap globally widened |
| stale identity / ticker collision | ambiguous/unresolved; no executable edge |
| same pool from two indexers | one deduped venue pool, two source receipts, no independent state |
| failed/cancelled request / connection gap | negative + backfill/continuity marker |

## Gate 2: quote / direct verification (DIN-03..05)

- Same route denominator, token decimals, input amount, time/slot and price side; stale mismatched quotes excluded from economic comparison.
- 0x vs Jupiter vs Titan may choose overlapping DEX liquidity; raw quote ancestry preserved. OpenOcean quote adds **zero independent underlying venue confirmations** unless on-chain liquidity identity actually differs.
- Selected quote has all required instruction/ALT or PTB metadata. No signer attached, no secret input, no transaction send.
- Solana QPR rooted pool/account evidence needs independently operated providers and consistent finalized/rooted context; two endpoints with one operator fail.
- Sui target must be correct Move type+package, object version/digest/checkpoint; legacy JSON-RPC fallback fails. Sui and Solana do **not** combine into LOCAL_ATOMIC cycles.
- Token-2022 unsupported transfer hooks/confidential fees/permanent delegate => typed reject pending reviewed issuer and decoder policy; no silent fallback to Token Program assumptions.
- Pyth Hermes without scoped key => no request issued; historical Odos adapter cannot be re-admitted by config rename.
- FlashCapitalGraph reads exact approved bank/pool loan constraints; borrowable amount bounded by actual bank and route limits, not just token presence. P0 zero protocol fee does not imply zero gas/compute/tip/rent/failure cost.

## Gate 3: paper and 24h campaign (DIN-06..07)

A 24h campaign is a distinct artifact, not '2 successful API calls'. All observations link back to unchanged `CampaignManifest` generation and actual source hashes. Record:
1. UTC campaign start/end, main/source SHA, entitlement/profile generation, config digest and source docs pins.
2. Provider calls by source/operator; attempted/admitted/physical success, cache hits, 200/429/401/5xx, bytes, rate-limit and auth blockers.
3. Discovered assets by canonical identity and representation, pools/books by true venue, dedup aliases and tombstones.
4. Fresh matched quotes and exact-state quorum counts, rejected stages with typed reasons; failed evidence retained.
5. Proposed loops sized by PR118 and FlashCapitalGraph; net after all known costs, simulation outcome and confidence/error bounds.
6. Raw-and-negative replay outputs, ledger consistency, storage pressure status, JSON summary and Markdown report.
7. **Final independent statuses:** read-only-real-data `PASS|BLOCKED`, exact `PASS|BLOCKED`, paper `PASS|BLOCKED`, production `BLOCKED`. No conflation.

Do not infer profitable arbitrage from a positive price residual unless the same intended amount and route after fees, liquidity and financing was verified. If none pass, report `0 qualified` rather than manufacture a pass.

## Suggested regression commands after RCN-00

```bash
python -m pytest -q tests/test_qpr01_campaign_identity.py tests/test_qpr02_data_plane.py tests/test_qpr03_source_intake.py
python -m pytest -q tests/test_gpr01_research_economic_graph.py tests/test_gpr01_v22_delta.py tests/test_gpr02_solana_parallel_radar.py tests/test_gpr03_sui_shadow.py
python -m pytest -q tests/test_dynamic_asset_resolution.py tests/test_dynamic_universe.py tests/test_dynamic_relations.py tests/test_dynamic_correlation_ledger.py tests/test_dynamic_flash_capital.py tests/test_dynamic_promotion_campaign.py tests/test_ton_radar_dynamic_universe.py
python -m pytest -q tests/test_pr_a_provider_truth_cleanup.py tests/test_native_cpmm_qualification.py tests/test_pr136_rooted_rpc_quorum.py
```

CI jobs and requirements-lock instructions are authoritative; commands here are named-file examples, not replacements for full CI. Run no live capture in CI unless explicitly bounded/authorized by the project's reviewed sandbox profile. Tests that need external credentials should block or skip with a reason, never be faked green.

## Milestone-specific success definition

- **RCN-00 PASS:** the actual GitHub PR head contains restored QPR/GPR + preserved main owners and focused tests pass.
- **DIN-00 PASS:** reviewed template supports bounded current-source physical admission; unreviewed rows remain disabled.
- **DIN-01/02 PASS:** real, cost-accounted, schema-pinned read-only source observations and deterministic negative replay on each chain.
- **DIN-03/04 PASS:** matching quote/PTB preview, independent provider lineage documented, zero signer/send.
- **DIN-05 PASS:** direct state and realistic simulated route economics; unsupported cases remain blocked.
- **DIN-07 PASS:** replayable 24h paper evidence and explicit blockers; **not automatically production-ready**.

Separately authorize later production work only after code security, independent state, durable storage, rollback, monitoring, release-bound soak and explicit human acceptance. This roadmap never grants live sending authority.
