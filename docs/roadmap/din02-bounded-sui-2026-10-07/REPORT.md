# DIN-02 bounded Sui diagnostic; exact and paper blocked

Review-only dependencies: RCN-00 #579 and DIN-00 #580. This independent DIN-02 branch targets main; no automatic merge.

The existing GPR-03 capture now defaults to the fetched current main SHA instead of its historical implementation base. An explicit `--base-sha` remains checked by the clean CampaignManifest factory. The historical base is retained separately as provenance. Existing Sui quotas are shared by real operator, including aliases; the narrow per-source response/node budgets, distinct Move candidate validation and sender-free GraphQL/checkpoint path are preserved. No legacy JSON-RPC fallback or signing/sending is introduced.

Actual bounded capture: 15 physical attempts, 46 indexed candidates, 99 structural rate observations. Quality counts: 3 accepted indexes/rates, 11 accepted read-only results, 1 transport error and 2 quota/admission denials. The counts are different stages, not 17 physical calls or 14 exact confirmations. The stricter shared operator bucket intentionally denied two later DeepBook book calls after its 12-call window was spent on indexed/checkpoint-object research. Do not split aliases to recover these denied calls.

The compressed public raw/negative journal export and original summary are committed under `capture/`; the existing offline replay verifies payload hashes, manifest, journal head, graph identity, decoder receipts and queue with zero network reads. Replaying this committed compressed export succeeded. Source pins are historical reviewed research contracts, not freshly verified published provider entitlements; per-source engineering caps remain explicit. 91 relevant existing/new admission tests passed. Canonical repository verification runs separately on this branch and its result is reported in the PR.

All exact qualification remains BLOCKED: reviewed decimals/full representation policy missing; legitimate independent non-smoke state providers missing; dynamic object depth/fee decoder missing. These are actual qualification blockers, not successful quorum. No 24h paper campaign or profit claim. Signing, sending, borrowing and production promotion remain disabled.

Replay:

```bash
python -m src.gpr_sui_shadow.campaign --replay docs/roadmap/din02-bounded-sui-2026-10-07/capture --output /tmp/din02-replay-new
```
