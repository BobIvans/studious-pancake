# AGG-07 — liquidations, lenders and rate markets

Base: `main@0c4f216a62d62b20f6fb4ec4bbd0548cea58df65`

Branch: `codex/agg-20260920-07`

## Scope implemented

This change is sender-free and default-off. It reuses the existing PR-020/MPR-2619
liquidation domain and MPR-2615 lender authority rather than creating another
runtime, capital owner, signer, sender or economic ledger.

### LIQ-01 / NF-072 / NF-144

- fresh protocol-specific eligibility is evaluated through existing liquidation adapters;
- stale oracle / unsupported protocol stays rejected;
- trigger-price evidence is bound to the exact target snapshot and can only prioritize
  a re-check; a forecast never grants liquidation permission;
- watchlists are deterministic and evidence-hashed.

### LIQ-02 / NF-145 / NF-146

- partial liquidation is bound to exact qualified financing evidence;
- final-message/simulation identity and borrow-instruction index must match;
- collateral asset, repayment asset, route capacity and exact financing repayment
  are checked before a candidate is accepted;
- lender fees are carried by the financing repayment and are not double-subtracted;
- batch selection prevents target and shared-resource double spending;
- dependent cascade work must be re-evaluated after the preceding observed outcome.

### CAPITAL-02 / NF-110 / NF-112 / NF-113

- Kamino plans consume pinned/conformance evidence instead of hard-coded fees;
- disabled/stale reserves, insufficient capacity, wrong borrow index and
  final-message mismatch fail closed;
- lender/size allocation selects the best feasible tested net result, not the
  largest principal;
- shared lender/exit reserves cannot be counted twice;
- Save/Solend/other lenders stay `BLOCKED_PROTOCOL` until official source,
  immutable pin, deployment, ABI/IDL, current liquidity and license/reuse evidence
  are complete.

### RATE-01 / NF-147 / NF-148

- protocol research has an explicit `BLOCKED_PROTOCOL` disposition;
- capacity release requires an observed positive capacity event and a closed,
  positive immediate route;
- permission-generation changes force requalification;
- one reserve cannot be used as independent lender and exit liquidity.

### RATE-02 / NF-074 / NF-149 / NF-150

- rate frames carry exact market, maturity, capacity and shared-resource identity;
- PT/YT identities and maturities must match;
- Exponent/source permission is evaluated independently from market math;
- future yield / maturity cashflow is retained for analytics but cannot finance
  current-message repayment;
- immediate rate parity uses executable depth and current cashflow only.

## Upstream disposition

- Kamino kLend: use the master-plan pin
  `38845294447623f6de3afc9dec29875f959f6f48` and unsigned instruction boundary.
  This PR does not claim live/deployed conformance by itself.
- Jupiter Lend: package/deployment/IDL are still not fully pinned by the supplied
  dossier, so no hypothetical executable liquidation API is introduced.
- Jupiter Lend AMM/capacity: dossier is research/UNSPECIFIED; kept blocked until a
  real supported API/program and dependency graph are proven.
- Save/Solend: research-only until a concrete official deployment/revision/license
  and exact repayment contract are pinned.
- Exponent: BSL/permission-gated; no production source is copied. The PR only adds
  generic evidence and exact-cashflow contracts.

## Tests added

- `tests/test_agg07_liquidation.py`
- `tests/lending/test_agg07_lending.py`

Negative coverage includes healthy/stale liquidation state, wrong borrow index,
insufficient exit, shared-resource conflicts, unproven lenders, reserve
double-count, Exponent permission gate, and future-yield exclusion.

## Operational status

`implementation_status = IMPLEMENTED_OFFLINE` for the new sender-free contracts.

`operational_status = BLOCKED` for any external Kamino/Save/Jupiter-Lend/Exponent
claim until the required deployed/source/conformance evidence is materialized.

No live capability, signing, submission or fund-spending path is enabled by AGG-07.
