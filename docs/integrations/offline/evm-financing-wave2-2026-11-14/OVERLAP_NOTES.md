# EVM financing wave-2 — overlap notes vs wave-1 and other lanes

Wave: 2026-11-14 (R09-L2 lane, docs-only). Branch `agent/evm-sui-dossiers-wave2`.

## What wave-1 already owns (cite, never re-pin)

- `docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/EVM_PROTOCOL_DOSSIERS.md`
  (PR #618, wave 2026-11-14): Morpho Blue + Aave V3 deployment pins, the 2026-10-08
  catalog (27 candidates), the `SOURCE_LEDGER.json` v2 entries, and `verify_bundle.py`.
  This wave **extends** those; the wave-1 file was NOT edited. All wave-1 Aave
  deployment addresses, license facts, and typed blockers are inherited verbatim.
- `docs/integrations/offline/providers-wave1-2026-11-13/` (PR #621): QUOTE/build
  routing dossiers (Titan/OKX/OpenOcean/Rango/Aftermath/Cetus-aggregator/7K/FlowX).
  Those are aggregator/SDK quote surfaces — no financing semantics. No overlap with
  this directory except the correlation note below.

## Overlap/correlation rules established or maintained by this wave

1. **Aggregator routes are not independent lenders.** Instadapp FLA / any future Fluid
   route reached through an aggregator must carry the same
   `underlying_capital_resource_id` as the direct pool route. Aggregator dossier
   surfaces (PR #621) must never be double-counted as financing capacity.
2. **PSM3 is swap surface only** — belongs in QUOTE/routing research, not financing.
3. **Deterministic-same-address != shared liquidity** (Aave 10/42161/43114/137 same
   Pool address; Fluid mainnet/arbitrum/base same Liquidity address). Each chain's
   deployment is its own capital resource.
4. **Ethereum Aave instances (Core/Prime/EtherFi/Horizon)** remain four separate
   capital resources (wave-1 rule).
5. **Selector policy**: no selector from third-party databases; derive from pinned
   ABI or `MISSING_DEPLOYED_ABI`.
6. **Code ownership**: `src/multichain/evm_financing.py` (Aave/Morpho/DODO/
   FlashMint adapters) is the canonical runtime owner of EVM flash obligations. This
   wave adds no adapter; Fluid/Euler would need NEW adapter classes there once pins
   close — do not repurpose Aave/Morpho classes.

## Cross-lane boundaries

- ton-wave1 lane owns `docs/integrations/offline/ton-wave1-2026-11-13/` and
  `src/.../ton_radar.py` — untouched here.
- Sui wave-2 (this PR) owns `docs/integrations/offline/sui-market-wave2-2026-11-14/`;
  no EVM facts were copied across domains (isolation flag stays true).
- R-07/R-02/R-03/R-05 remain the qualification owners; this lane only pins sources.
