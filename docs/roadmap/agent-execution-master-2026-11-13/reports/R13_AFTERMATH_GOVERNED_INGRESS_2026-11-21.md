# R13 Aftermath offline-to-governed quote ingress — lane report (PR #667, slice 1)

Date: 2026-11-21
Lane: PR #667 "Sui quote/state integration vertical slice" (`codex/real-data-multilender-integration-2026-11-21`)
Task: first deliverable of the #667 trigger Phase 2 — the Aftermath offline-to-governed quote adapter.

## 1. What was delivered

The PR #661 offline normalizer validated Aftermath `POST /api/router/trade-route` responses into kernel `NormalizedProviderQuote` evidence but shipped no ingress (funnel/boot wiring was explicitly DEFERRED). This slice adds only that missing glue, in a disjoint path, with no duplicate owner:

- **`src/gpr_sui_shadow/providers/aftermath_ingress.py`** (new): retained-payload ingest → existing normalizer → frozen R13 kernel race.
- **`tests/test_r13_aftermath_ingress.py`** (new): 23 unit tests, zero network.
- **`config/format_targets.txt`**: one added line (black gate target).
- **This report** + one readiness-cell edit in `SUI_ASSET_AND_PAIR_PLAN_RU.md`.

Nothing else changed. `aftermath.py` (PR #661 owner), the kernel (`src/execution/quote_build_kernel.py`, frozen `r13.quote-build-kernel.v1`), `src/gpr_sui_shadow/providers/__init__.py` (GPR-03 checkpoint owner) and all N09-owned NAVI/multichain paths are untouched.

## 2. Reuse map (no duplicate owner created)

| Concern | Reused owner | Not duplicated |
|---|---|---|
| Response normalization, CoinTypes, BigInt amounts, route legs, pool ids, fees, typed errors | `src/gpr_sui_shadow/providers/aftermath.py` (`normalize_aftermath_trade_route_response`, `normalize_via_transport`) | no second parser/decoder |
| Quote comparability, ranking, pool dedup | `src/execution/quote_build_kernel.py` (`QuoteRaceResult.build`, `PoolIdentityDeduplicator`) via existing seams `build_kernel_race_request` / `kernel_race_inputs` | no second quote kernel, no second dedup |
| Live-capture gate | `aftermath_live_capture_verdict()` (always BLOCKED) | gate not weakened, no PASS path added |
| Sui provider quorum gate | `live_binding_verdict()` / `require_independent_pair()` (GPR-03) | typed `ValueError` strings preserved verbatim |
| State provenance | GPR-03 offline pair evidence (`OfflinePairVerdict` discipline) as the intended source of `AftermathStateEvidence` | no second state plane, no synthesized checkpoint |

## 3. Typed contract of the new ingress

- `ingest_offline_payload(payload, *, request, received_at_ns, state_evidence=None, competing_quotes=(), now_ns=None)` — deterministic offline path; `now_ns` defaults to `received_at_ns` so no replay synthesizes a clock.
- `ingest_via_transport(transport, ...)` — the existing gate verdicts run BEFORE the transport is invoked; no transport can execute while BLOCKED, so every live attempt today raises `AftermathIngressError(LIVE_READ_NOT_AUTHORIZED, <exact gate reasons>)`. `None` stays a typed `DISABLED` refusal.
- `AftermathStateEvidence` — validated caller-supplied checkpoint provenance (quorum checkpoint sequence/digest, capture request/response hashes, provider/correlation identity, capture time, source generation, evidence ref). Attaches `QuoteFreshness.checkpoint_sequence` via pure provenance join; without it the checkpoint stays UNKNOWN (`None`, never zero) and blocker `AFTERMATH_STATE_EVIDENCE_REQUIRED` is recorded. The trade-route payload can never supply a checkpoint.
- `provider_lane_status()` — deterministic typed status ladder (below).
- Evidence state of all outputs: `INGRESS_OFFLINE_COMPARABLE_UNQUALIFIED`; per-entry state stays the adapter's `ADAPTER_BUILT_OFFLINE_UNQUALIFIED`; `execution_authority` stays kernel-False.

## 4. Provider status ladder (typed, as of `r13.aftermath-ingress.v1`)

| Stage | Status | Reason |
|---|---|---|
| DOCUMENTED | ACHIEVED | wave-1/wave-2 dossiers + `AFTERMATH_ADAPTER_SCHEMA_PIN` |
| ADAPTER | ACHIEVED | `r13.aftermath-adapter.v1` (PR #661 offline normalizer) |
| BOOT_WIRED | ACHIEVED | `r13.aftermath-ingress.v1` offline governed ingress (PR #667) |
| COMPARABLE | ACHIEVED | kernel race comparable offline (exact amount/type binding) |
| LIVE_READ | BLOCKED | `AFTERMATH_LIVE_CAPTURE_NOT_AUTHORIZED`; `LIVE_SUI_PROVIDERS_NOT_AUTHORIZED` |
| ROOTED | BLOCKED | `LIVE_SUI_PROVIDERS_NOT_AUTHORIZED` (independent provider quorum) |
| BUILDABLE | NOT_STARTED | R-03 builder owner; quote is not a PTB (add-trade separate) |
| R02_QUALIFIED | BLOCKED | no qualified capital evidence; NAVI qualification owned by DAG N09 (R02-CAP-C) |
| R05_SIMULATED | NOT_STARTED | R05 exact simulation owner |
| R06_PAPER_QUALIFIED | BLOCKED | only the canonical R06/QPR paper service can promote |

## 5. Tests (exact counts)

- `tests/test_r13_aftermath_ingress.py` — **23 passed** (`pytest -q`, offline). Coverage: fail-closed stance (None transport DISABLED, transport attempt refused with both gate reasons, deterministic gate verdict, correlated-pair reason preserved verbatim, env-var cannot flip, no network imports); offline positives (kernel race winner, exact CoinTypes, integer base units, route leg order, canonical `POOL_OBJECT_ID` identities, correlation group/lineage/pool ids, fee components with UNKNOWN inclusion, raw response hash + request fingerprint, `execution_authority=False`); state evidence binding (attach, 8 malformed-evidence typed refusals, non-evidence object refusal, payload never synthesizes checkpoint); race/dedup reuse (correlated loss reason, independent clean win/loss, `IndependenceVerdict` boundaries); status ladder; deterministic replay (identical records + race fingerprint); regression (no boot export, adapter surface untouched, no N09-owner imports).
- Regression subset: `test_r13_aftermath_adapter.py` + `test_r13_kernel_contract.py` + `test_r13_quote_race_contract.py` — **95 passed**.

## 6. Offline replay receipt

Fixed inputs: fixture `tests/fixtures/r13_aftermath_adapter/trade_route_exact_in.json`, request 1.5 SUI (MIST) → USDC ExactIn, `received_at_ns = 1_736_000_000_000_000_000`, no state evidence:

- `race_fingerprint` = `d83f61065dc67f36ddb40bd1adecc35d9e9a610f12333a739e885bbd6282c988`
- `raw_payload_sha256` = `ac2d75c6c5047564f82e99120f446cd9b73933a913485cf57ded08b68071af43`
- `blockers` = `("AFTERMATH_STATE_EVIDENCE_REQUIRED",)` — checkpoint unattached, unknown is never zero.

Same inputs reproduce byte-identical results (pinned by `TestDeterministicReplay`).

## 7. Changed paths / provenance

- Base (PR #667 fork point): `ea204222`
- Merged current origin/main: `0a0c8ad9` (merge commit `efc7b0c3` on this branch)
- Implementation commit: `43fb3b4b` (`feat(#667): Aftermath offline-to-governed quote ingress (R13 vertical slice)`)
- Changed paths: `src/gpr_sui_shadow/providers/aftermath_ingress.py` (new), `tests/test_r13_aftermath_ingress.py` (new), `config/format_targets.txt` (+1 line), this report, `docs/strategy-expansion/2026-11-21/real-data-multilender-integration/SUI_ASSET_AND_PAIR_PLAN_RU.md` (§3 Aftermath readiness cell).
- Quality gates on the new module/tests: black (formatted clean), flake8 clean, mypy clean in isolation (`--follow-imports=skip`; 7 pre-existing errors live in `src/qualification_campaign/sources.py` and reproduce for the existing `aftermath.py` baseline); `scripts/validate_authority_map.py` → `valid: true`.

## 8. Blockers / out of lane (typed, not silently dropped)

- `LIVE_READ` / `ROOTED`: live Sui reads stay BLOCKED until the existing `CAMPAIGN_START_V1` + QPR/provider governance independently returns PASS for the exact source profiles and budgets; this PR is not an authorization and adds no PASS path.
- Pre-existing on current `origin/main` (reproduced on pristine `origin/main`, untouched by this branch): `tests/test_gpr03_remediation.py` fails (11 tests, `ValueError: unresolved synthetic path` from `src/research_economic_graph/registry.py`). Outside this lane's owners; reported here for the owner of that path.
- `R02_QUALIFIED` (NAVI/DeepBook lender evidence): owned by DAG N09 / R02-CAP-C; not touched.
- `BUILDABLE`: quote ≠ PTB; `add-trade` composition belongs to the R-03 builder owner.
- Follow-up slices (one provider at a time, per the #667 trigger): Cetus Aggregator V3, 7K/Bluefin7K, FlowX, OKX DEX, Rango, direct DeepBook quote adapters; Phase 3 asset/pair universe expansion; R02/R03/R05 handoffs.

PR: https://github.com/BobIvans/studious-pancake/pull/667 (kept Draft; no merge without explicit human approval per AGENTS.md rule 11).
