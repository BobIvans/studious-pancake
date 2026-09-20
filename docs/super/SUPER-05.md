# SUPER-05 — orderbook, LST/dynamic and lending strategy closure

Status: **VERIFIED_OFFLINE implementation closure / operationally UNQUALIFIED / live disabled**.

SUPER-05 aggregates **W2-13 + W2-14 + W2-15**. This PR is an integration
closure over accepted owners; it does not create a second orderbook, LST,
liquidation, rate-market, signer, sender, compiler, capital authority or
economic ledger.

Base at branch creation:
`main@27875850a88edf102c904e31955e0df8b78b13b4`.

## Reused accepted owners

- **AGG-06 / PR #507**, merge `d341024c9e76851a42f63370a56de3922539a8d3`
  - W2-13 PR-108/109/110: CLOB window, Phoenix/OpenBook quote seams and
    conservative CLOB↔AMM admission.
  - W2-14 PR-111/112/113: immediate LST/redemption, basket/LP parity,
    dynamic-fee/Token-2022, migration and post-swap state.
- **AGG-10 / PR #500**, merge `de483bc3084a87d2b3f34830bdecf94ea0e4e63d`
  - W2-14 PR-118: opt-in/orderflow observation, route coverage hypotheses and
    oracle-divergence signals.
- **AGG-07 / PR #499**, merge `a04662f885476d73c381984ead4ef694eb83ad3d`
  - W2-15 PR-114/115: liquidation eligibility/forecast and flash-funded
    liquidation/cascade conflict handling.
  - W2-15 PR-116/117: capacity-aware lending research and matched-term rate
    parity.

MPR-2621 remains the underlying LST immediate-exit authority consumed by
AGG-06. Existing `src.providers.orderbook` remains fixture-only/quarantined;
SUPER-05 does not silently promote it to runtime/live authority.

## Exact package ownership

SUPER-05 owns eleven child scopes and 26 primary NF:

- W2-13: PR-108 (NF-070, NF-120), PR-109 (related-only OpenBook adapter),
  PR-110 (NF-138).
- W2-14: PR-111 (NF-073, NF-121, NF-122, NF-139, NF-151), PR-112
  (NF-140, NF-141, NF-153), PR-113 (NF-119, NF-142, NF-143), PR-118
  (NF-081, NF-152, NF-154).
- W2-15: PR-114 (NF-072, NF-144), PR-115 (NF-145, NF-146), PR-116
  (NF-147, NF-148), PR-117 (NF-074, NF-149, NF-150).

`src/super05_strategy_closure.py` makes this mapping executable. Every child
points at the existing canonical module and concrete symbol(s); duplicate or
missing primary ownership is a hard verification failure.

## Operational blockers intentionally preserved

Implementation closure is not operational qualification. The verifier retains:

1. `SUPER05_ORDERBOOK_RUNTIME_FIXTURE_ONLY` while the historical orderbook
   package is quarantined and lacks current deployed runtime promotion.
2. AGG-06 external evidence requirements: current deployment identity, exact
   upstream/license decision, independent amount-bound conformance vectors,
   recorded/loaded-state evidence and family-specific qualification.
3. AGG-07 protocol blockers, including Jupiter-Lend AMM uncertainty,
   Save/Solend source/deployment/license evidence, Exponent production reuse
   permission and deployed Kamino conformance.

These blockers are not converted to PASS by this PR.

## Safety boundary

- no private key or signer access;
- no transaction/RPC/Jito submission;
- no remote resource mutation;
- no account funding;
- no automatic family promotion;
- no profitability claim;
- `live_enabled=false` and `release_claim_allowed=false` are hard outputs of
  the SUPER-05 closure report.

## Verification

`scripts/verify_super05_strategy_closure.py` checks:

- exact 11-child and 26-primary-NF ownership;
- importability of every canonical owner symbol;
- AGG-06/07/10 coverage artifacts contain the required NF;
- all reused owner artifacts remain default-off;
- the existing orderbook quarantine is represented as an operational blocker,
  not hidden.

The verifier is wired into repository verification. Focused tests also mutate
coverage/live evidence to prove the gate fails closed.

## Rollback

Revert this closure PR. No financial state, remote resource, capability
activation or schema migration is introduced. AGG-06, AGG-07 and AGG-10 remain
their independent canonical owners.
