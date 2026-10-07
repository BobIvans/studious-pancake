# GPR-03 Sui parallel shadow handoff

GPR-03 is implemented and tested for bounded discovery, structural references,
independent checkpoint/object qualification and replay. It remains read-only and
shadow-only. Actual campaigns produced no HARD_BOUND receipt and no verified
anomaly. GPR-04 implementation has not started.

## Exact lineage and evidence

Published GPR-01 base: `8c59759b491b6318f259138671dccfea25f2752e`.
Isolated branch: `impl/gpr03-sui-shadow-2026-10-06`.
Final real capture head: `14f3884ace69a2382c47fad5b916e76c86dc153c`.
Final tested code head: `315fd7bb07fa8f1df5025c1ed30163150f514e55`.
The final code adds a fail-closed finite known-book parameter fence; the captured
requests already used exactly depth 20 / level 2 and remain unchanged.
The final handoff commit and its verified remote head are recorded after commit
in the external `/workspace/shared/gpr/GPR-03_HEAD_RECEIPT.json`; a tracked file
cannot contain its own final commit SHA.

| Immutable slice | Clean capture/code head | Campaign ID | Physical reads | Candidates / rates |
| --- | --- | --- | ---: | ---: |
| Initial negative | `da737d41d95730981a05f55e21c971005f6e17bf` | `e7e030c88934b6c360b492dbbf6c38730c5fe5ff3b073725285728894d55caf1` | 5 | 0 / 0 |
| Corrected intermediate | `d31ceb64d425a4156d89f7314b82f6927c729c19` | `2f9fa430ddb66b0b83278df0eeef67b88c4f24dfba64e937fed696214a594617` | 8 | 46 / 0 |
| Final corrected | `14f3884ace69a2382c47fad5b916e76c86dc153c` | `ac7e52f1102539ee819e2b673eccdab5154cc7b0dff59fb263abea2ce0f2c62d` | 8 | 46 / 99 |

Public portable evidence is in [gpr03-evidence/INDEX.json](gpr03-evidence/INDEX.json).
Each slice includes its exact manifest, summary and deterministic compressed
expanded event/raw evidence. The index binds SHA-256 and byte lengths, including
uncompressed export hashes. Combined compressed exports are 418,725 bytes.
SQLite stores, locks, dependencies, credentials, private headers and proxy/CA
values are excluded. Runtime credential-value and anonymous-header audits passed.
The initial slice predates explicit public header capture; its five records are
identified in the index. All original failures remain immutable.

All three published gzip exports reproduced identical graph/queue state with
zero network reads. The final replay reproduced 16 queue entries. Example from
the repository root, using a new output directory:

```sh
.venv/bin/python -m src.gpr_sui_shadow.campaign \
  --replay docs/roadmap/gpr-parallel-radar-rnd-2026-10-06/gpr03-evidence/final-corrected \
  --output /tmp/gpr03-final-offline-replay
```

## Implemented behavior

The Sui intake uses the published GPR-01 registry, seed, ResearchEconomicGraph,
VerificationQueue, CampaignManifest and durable evidence contracts. Sui candidate
types are separate; Solana QPR candidate/domain checks are preserved. Index
relations and structural helpers remain `LOCAL_SIGNAL` / `DISCOVERY_ONLY`, with
independent heat. Original transport relations retain their non-atomic
`REBALANCE_ONLY` / `CROSS_CHAIN_SIGNAL` axes.

Source profiles pin exact public read endpoints, schema/adapter generations,
operator/correlation identity, request shape, size/node caps, bounded row scans
and attempt caps. All Mysten aliases share one reviewed quota generation and one
12-request/cost-unit, 60-second, concurrency-one pool. Source generations remain
distinct. Final quota retention shows five Mysten requests spent; each other
operator spent one. In-memory and durable restart tests verify aggregate denial
before physical issuance. No retries, redirects or unrestricted queries occur.
Transport keeps TLS/CA/proxy controls and supported gzip/deflate bounds. Concurrent
collect calls serialize admission and wire retention. Replay binds parsed data
to retained response bytes and prevents source/venue relabeling.

DeepBook discovery includes the nine seeded exact pool identities and three
bounded known stable-family book references. Aftermath and Cetus have separate
bounded normalizers; Scallop captures conversion/supply/borrow inputs without
substituting lending APY for a staking exchange rate. GraphQL uses finite official
source-pinned checkpoint and checkpoint-scoped object/coin metadata templates;
no legacy Sui JSON-RPC or live PTB executor is present.

The generation-bound HARD_BOUND gate reconstructs retained successful fresh
physical captures from at least two independent non-smoke governed operators,
reviewed network genesis, exact pool Move package/module/type and checkpoint,
object version/digest, actual coin types, BCS metadata decimals/UID, full material
issuer/origin/bridge representation proof, depth, lot/tick and fee evidence.
Standard exact `0x2::coin::CoinMetadata<T>` BCS is decoded with bounded canonical
lengths; lookalike packages and rehashed wrong decimals fail closed. The pool
layout/depth/fee decoder and identity/representation policies require explicit
reviewed bindings. This slice supplies no mainnet pool decoder or promotion.
Deterministic positive fixtures are test-only contracts.

## Real results and limits

| Source | Final measured result | Meaning |
| --- | --- | --- |
| DeepBook `/get_pools` | HTTP 200; 13,630 bytes; 26 rows; all 9 seeded IDs present | Indexed discovery; exact depth/fee qualification unavailable |
| Cetus stats pools | HTTP 200; 45,577 bytes; 20 exact-type rows | Measured `code=0/data.lp_list` contract; discovery only |
| Scallop SDK index | HTTP 200 gzip; 69,898 decoded bytes; 33 rows / 99 rates | 33 each conversionRate, supplyApy, borrowApy; source updatedAt `2026-10-06T05:50:05.713Z`; unit/time qualification still required |
| DeepBook known books | 3 HTTP 200 snapshots; 251 / 364 / 251 bytes | Indicative bounded best levels and rational spreads retained; no checkpoint depth/fee proof |
| Aftermath pool index | HTTP 200 gzip exceeds pinned 2 MiB decoded cap | Successful endpoint availability with a bounded collection failure; no complete body or inferred markets |
| Sui GraphQL | HTTP 400; 43-byte text header error | Actual prepared/issued POST contains 123 body bytes and Content-Length `123`; deployed request interoperability unresolved |

The final graph admitted 33 registered pool discovery relations and structural
references only for exact registered Move types. Pool index observations cover
WUSDC_ETH_ORIGIN, native USDC, both requested USDT representations, suiUSDe,
USDsui, XBTC and ZWBTC. Scallop supplies indexed inputs for afSUI, haSUI, vSUI,
scaSUI and XAUM among registered assets. Those inputs are lending/share helpers,
not measured LST market residuals. sSUI, XAU and USDC_SOL_PORTAL_ON_SUI did not
receive comparable verified market/oracle measurements in this slice.

Indexed WUSDC/USDC best bid/ask were `0.10001` / `99.989`; Wormhole-USDT/USDC
`0.987` / `1.0785`; Sui-Bridge-USDT/USDC `0.010001` / `1.001`. Sizes, timestamp,
level counts and exact rational midpoint spreads are retained in the summary.
These sparse/wide index snapshots justify prioritizing depth/fee and quote-unit
measurement; they establish no executable opportunity. There is no oracle binding
for XAUM/XAU, no paired verified LST rate/market quote and no qualified
DeepBook-versus-AMM/router residual.

GraphQL supplied no checkpoint context, so all nine dependent exact object reads
were correctly unissued. Every seed remains `BOOK_DEPTH_UNQUALIFIED`.
Public sources are smoke-only and cannot form quorum. Zero HARD_BOUND receipts,
zero promoted candidates and `measured_anomalies: null` are explicit outcomes.

## Independent verification

Final selected suite: **355 passed**, zero failed/skipped, with sockets disabled:
86 GPR-03 tests and 269 relevant GPR-01/QPR/multichain regressions. Root separately
reran the preceding 351-check subset at the exact final capture head and passed;
the final code adds four query-fence negative checks. Commands:

```sh
.venv/bin/python -m pytest -q -o log_cli=false --disable-socket --allow-unix-socket \
  tests/test_gpr03_sui_shadow.py tests/test_gpr01_research_economic_graph.py \
  tests/test_gpr01_v22_delta.py tests/test_qpr01_campaign_identity.py \
  tests/test_qpr02_data_plane.py tests/test_qpr03_source_intake.py \
  tests/test_shadow_market_data_aggregation.py tests/test_shadow_arbitrage_graph.py \
  tests/test_agg11_multichain_execution_models.py tests/test_agg12_multichain_qualification.py
.venv/bin/python -m mypy --follow-imports=silent src/gpr_sui_shadow
.venv/bin/python -m flake8 --select E9,F63,F7,F82 src/gpr_sui_shadow tests/test_gpr03_sui_shadow.py
.venv/bin/python -m black --check src/gpr_sui_shadow tests/test_gpr03_sui_shadow.py
git diff --check
```

Seven new modules pass the scoped type check. Unscoped import checking exposes
pre-existing QPR source annotations; those owners were preserved. No dependency
or lockfile changed. The independent `.venv` uses the existing locked requirements
and shared immutable UV cache; neither the base nor Solana environment is mutated.

Changed files are isolated additions: seven `src/gpr_sui_shadow/*.py` modules;
`config/gpr03_sui_source_pins.json`; `tests/test_gpr03_sui_shadow.py`;
`GPR-03_SOURCE_CONTRACTS.md`, this handoff, `GPR-03_PROBLEMS.md` and the ten files
under `gpr03-evidence/`. The final external receipt lists exact paths.

## Recommended next actions

Resolve the measured GraphQL request interoperability and configure independently
operated non-smoke state sources through environment settings. Bind reviewed
network/representation/decimals and actual production Move layouts before any
HARD_BOUND attempt. Source-pin a bounded targeted Aftermath read rather than
expanding an unmeasured bulk response cap. Measure comparable exact-unit quotes,
DeepBook dynamic book/fees and structural/oracle inputs for the prioritized
families, including the absent portal-USDC and gold comparisons.

Compare this evidence with GPR-02 before proposing GPR-04/05/06/07/08 work.
No GPR-04+ implementation, signer, sender, submission, live capital, PTB execution
or production promotion is enabled.
