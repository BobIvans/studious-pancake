# SX-03 — Curve LLAMMA protocol dossier (banded collateral / soft liquidation)

Date: 2026-11-14. Lane: SX-03 (research/shadow only; execution class
`CONDITIONAL_HYPEREDGE`). Companion module:
`src/strategy_evolution/llamma_band_math.py` (independent implementation, no
third-party code reused).

## 1. Source pins (AGENTS.md rule 4)

| Source | Location | Status | Notes |
|---|---|---|---|
| Official AMM contract source | `curvefi/curve-stablecoin`, branch `master`, path `curve_stablecoin/AMM.vy`, retrieved via `raw.githubusercontent.com` 2026-11-14 | **VERIFIED RETRIEVED** (full formula set extracted); commit SHA pin **PENDING** (github.com unreachable at authoring time — typed blocker below) | Branch-level pin; re-verify SHA before any qualification-tier use |
| License of the above repo | `LICENSE` at repo root, retrieved 2026-11-14 | **PROPRIETARY — "(c) Swiss Stake AG, 2022-2026", all rights reserved; "no license, right of reproduction or distribution or other right … is granted or implied"** | **No code was copied, vendored or translated from the repo.** The research module below re-derives the documented mathematical relations (band geometry, invariant, quadratic) as our own expression. Mathematical formulas/relations are not copyrightable expression; any future integration MUST re-review this license and obtain rights if code-level reuse is ever desired. |
| crvUSD whitepaper | `https://classic.curve.finance/files/crvusd-whitepaper.pdf` | **PENDING RETRIEVAL** (connection timeouts at authoring time; typed blocker below) | Referenced as the canonical math narrative; band semantics cross-checked against the retrieved contract documentation instead |
| Official docs hub | `https://docs.curve.finance/developer/crvusd/overview` | Referenced (not retrieved this session) | |

## 2. Documented relations used (re-derived, not copied)

All amounts use 18-decimal raw units; prices are WAD (`10**18`) scaled. `A > 1`
is the band concentration parameter; `p_base` is the (rate-multiplied) base
price of the band grid; band `n` spans
`[p_up(n+1), p_up(n))` where

1. `p_up(n) = p_base * ((A-1)/A)**n` — geometric band edges; on-chain this is
   computed via a WAD exp approximation of the same relation (`power = -n *
   ln(A/(A-1))`), and the whole grid shifts when interest accrues.
2. `p_down(n) = p_up(n) * (A-1)/A = p_up(n+1)`.
3. Within a band with collateral `x` and stable `y`, the invariant is
   `(f + x) * (g + y) = Inv`, with
   `f = A*y0*p_o^2 / (p_up * WAD)`, `g = (A-1)*y0*p_up / p_o`, and
   `Inv = p_o * A^2 * y0^2` where `y0` solves the pinned quadratic
   `D = b^2 + 4*A*p_o*y*x/WAD`, `b = (A-1)*p_up*x/p_o + A*p_o^2*y/(p_up*WAD)`,
   `y0 = (b + sqrt(D)) * WAD / (2*A*p_o)`.
4. Mid-band price `p = (f + x*WAD) / (g + y)` with the contract's explicit
   edge cases (`x = 0` → `p_o^2/p_up^2`-form; `y = 0` → same form with
   `p_up' = p_up*(A-1)/A`).
5. Dynamic fee: at least the static fee, grows toward `10^18/4` scale with the
   cube of the oracle-vs-band-price ratio; instantaneous oracle change is
   capped (~`2^(1/3)` per update) so fees stay bounded (<50%).
6. Active band follows `p_oracle`: bands above the oracle hold collateral,
   bands below hold stable; when the oracle falls across a band edge, the
   crossed band's collateral converts to stable (soft liquidation / LLAMMA
   spread), which is the arbitrage/liquidation surface of this family.

**Research-model simplifications (documented, tested):** (a) band edges use the
exact rational geometric relation, not the on-chain WAD-exp approximation;
(b) swap fee is applied on the input leg; the contract applies an "antifee" on
the output leg of the reciprocal direction — both conserve assets with a
bounded fee; (c) oracle transitions convert the full crossed-band inventory at
the crossed boundary price (single-user band model); per-user share accounting
is out of scope until an account-state dossier exists.

## 3. Data dependencies (to prove before any tier promotion)

- Per-market AMM state: `A`, `BASE_PRICE` (+ rate/`rate_time`), `active_band`,
  per-band `x`/`y` inventory, fee — must come from rooted, revision-pinned
  account state (`state_generation` mandatory).
- Oracle price + freshness (typed `oracle_stale` gate; ≤ 30 s research bound).
- Controller/AMM revision pin + license re-review (typed `market_not_pinned`).
- **Typed blockers recorded:** `curve_license_proprietary_no_code_reuse`
  (resolved by independent implementation; re-review before integration),
  `whitepaper_pdf_unretrieved_2026-11-14`, `source_commit_sha_pin_pending`,
  `per_market_account_state_unproven` (no rooted market state in main).

## 4. Strategy family status after this lane

- CREDIT-LLAMMA moves STUB → PARTIAL_OWNER (research): exact band-edge
  arithmetic, active-band determination, invariant-based band pricing with the
  pinned quadratic, oracle-crossing soft-liquidation transitions, typed
  stale/state gates, and an explicit non-constant-product guard are now
  implemented and tested offline.
- Still missing for any promotion past research: official numeric example
  vectors (whitepaper retrieval), per-market rooted state, controller revision
  pin, and the license re-review for any deeper integration. No oracle price
  is ever treated as an executable quote; liquidation eligibility integration
  must go through the shared exact evaluator owners, not this module.
