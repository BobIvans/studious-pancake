# MPR-42 — Exact Economic, Transaction and Finalized-Settlement Authority

This PR starts the MPR-42 closure slice as an additive, sender-free, fail-closed foundation.

It does **not** enable live trading, signing, transaction submission, wallet loading, RPC polling, Jito submission or unrestricted live capability.

## Scope

The new boundary models one immutable economic truth chain:

1. canonical transaction plan;
2. immutable serialized message digest;
3. exact fee/message proof;
4. capital reservation proof;
5. final exact simulation proof;
6. expected/simulated/paper-realized/live-realized PnL layers;
7. finalized settlement evidence;
8. ambiguity quarantine for unknown or partial outcomes.

## Safety invariants

- Every monetary value is a strict integer atomic unit.
- Float, NaN, infinity and bool-as-int values are rejected at the boundary.
- Compiled message, final simulation, fee proof, reservation and settlement must reference the same immutable message hash.
- Paper PnL, simulated PnL and live realized PnL are separate layers.
- RPC/Jito ACK, submitted and landed statuses are not settlement.
- Live-realized PnL requires finalized signature, slot, payer delta, token delta and ledger evidence.
- Unknown or partial outcomes must enter quarantine and block capital reuse.
- Unrestricted live remains forbidden.

## Added files

- `src/mpr42_exact_economic_settlement_authority.py`
- `scripts/verify_mpr42_exact_economic_settlement_authority.py`
- `tests/test_mpr42_exact_economic_settlement_authority.py`

## Verification

```bash
python -m compileall -q src scripts tests
python scripts/verify_mpr42_exact_economic_settlement_authority.py --strict --json
python -m pytest -q tests/test_mpr42_exact_economic_settlement_authority.py
```

## Follow-up wiring

Later MPR-39/40/41/43 work should physically wire this boundary into the installed paper/shadow runtime, provider plane and durable economic authority. This PR only establishes the exact economic/settlement contract and regression suite.
