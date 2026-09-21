# PR-355 — Evidence-Native Financial Mechanism OS

## Current truth

Implementation base: `main@d8d6d9079689efdddf77ce373120675255a99327`.

Merged predecessors are reused rather than rebuilt:

- GitHub #531 / strategy-evolution PR-353 owns EVO-01…EVO-09 and NF-1017…1088.
- GitHub #532 owns the PR-353 final strategy-closure evidence gate.
- GitHub #533 / roadmap PR-354 owns RND-00…RND-11 and NF-1089…1184.
- EVO-09 remains the canonical residual-anomaly/bot-feedback loop.

No new permanent NF IDs are allocated by PR-355. `NXF-001…NXF-072` remain provisional requirement identities.

## New specializations

PR-355 extends the existing `src.mechanism_discovery` research owner with:

- exact Financial Claims / Cashflow IR;
- Liquidity Shape / Hybrid Execution IR;
- programmable cash and synthetic-dollar rights/backing models;
- RWA/NAV/eligibility/custody lifecycle;
- Hub/Spoke shared-credit capacity;
- mechanism fingerprints and local-only vs transfer comparison;
- budget-aware frontier scheduling with selection-bias evidence;
- deterministic ResearchReceipt and optional mock proof contract;
- mock/testnet/zero-cost research-resource economy;
- incident-derived security admission;
- bounded causal-intervention twin;
- nine default-off MarketPacks.

## EVO-09 semantic repair

The existing owner was repaired in place:

1. missing/unsent realized PnL remains `None`, never implicit zero;
2. `actual_landed` remains unknown unless explicitly observed;
3. residual clustering requires explicit stability, FDR and persistence evidence;
4. financial score atoms are no longer mixed with latency milliseconds or PPM units;
5. secrets/signed payloads remain rejected.

## MP-N01 Boros

The first vertical is executable with deterministic local fixtures:

`fixture rows → point-in-time CashflowSpec → fixed/floating forecast → later mature label → error → ResearchReceipt`.

The fixture demonstrates pipeline semantics only. Final verdict is `BLOCKED_EXTERNAL` because the primary Boros historical-data pin, entitlement/terms and real point-in-time corpus were not materialized. Synthetic/fixture success is not reported as qualification.

## MarketPack state

All MP-N01…MP-N09 are checked in `DISABLED`; allowed modes are read-only/offline/replay/shadow research only. Bunni remains incident/reference-only and cannot become a production adapter through this PR.

## Upstream policy

No external implementation is copied or vendored. Pendle/Boros, Arrakis HOT, Bunni, M0, Ethena, Centrifuge, Aave Horizon/V4, x402 and SP1 remain `REFERENCE_ONLY` until exact immutable pins, artifact-level license/terms, entitlement and conformance evidence are admitted.

## Safety

The following remain false: `production_ready`, `live_enabled`, signer/submission access, wallet funding, remote mutation, automatic promotion and automatic capital increase. MarginFi remains `PAUSED`; the Slumlord low-capital requirement remains `REQUIRED`.

## Rollback

Rollback is config-first: disable PR-355 packs, detach optional consumers, restore previous research-model selection, quarantine invalid evidence, and preserve append-only raw/evidence/receipt history. No fund recovery or transaction reversal is needed because PR-355 adds no effects.
