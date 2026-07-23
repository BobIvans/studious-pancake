# MPR-04 — Protocol-bound atomic economic execution

This PR starts the V4 **MPR-04 — Protocol-bound atomic economic execution** cutover as a focused, sender-free acceptance gate.

The V4 roadmap assigns MPR-04 the protocol/economic boundary: canonical program registry, deployed protocol attestation, ATA/wSOL/rent invariants, exact instruction firewall, blockhash/current-height freshness, serialized transaction sizing, raw-state simulation and decoder-owned conservative PnL.

## Why this slice exists

The V4 audit reproduced unsafe green decisions from fabricated or internally inconsistent evidence:

- duplicate `marginfi.borrow` / `jupiter.leg_a` instructions;
- expired `last_valid_block_height`;
- simulation evidence without raw account/economic state;
- economic proof constructed from caller-supplied deltas/profit;
- rent/contingency not reducing conservative PnL;
- flash fee not bound to exact repayment formula.

This slice adds a single offline gate that fails closed on those classes before any runtime can claim a protocol-bound candidate is sender-free ready.

## Added files

- `src/mpr04_protocol_bound_economics.py`
- `tests/test_mpr04_protocol_bound_economics.py`
- `.github/workflows/mpr04-protocol-bound-economics.yml`

## Implemented acceptance contract

The gate requires all of the following to be bound into one attempt generation:

1. `ChainProgramRegistry` validates canonical Token-2022, legacy SPL, System, wSOL and associated-token identities.
2. `InstructionFirewallEvidence` requires exact cardinality and order for critical protocol roles:
   - `marginfi.borrow`
   - `jupiter.leg_a`
   - `jupiter.leg_b`
   - `marginfi.repay`
3. `BlockhashFreshnessEvidence` rejects expired or too-close blockhashes using current block height and safety margin.
4. `SerializedTransactionEvidence` computes signed wire-size budget from unsigned bytes and signature slots.
5. `ExactSimulationArtifact` requires successful simulation with bounded raw returned account state.
6. `DecoderOwnedEconomics` must be bound to the simulation hash and decoder version.
7. Repayment must satisfy `repayment = principal + flash_fee`.
8. Conservative PnL deducts repayment, network fee, priority tip, rent loss, transfer fee and contingency.
9. Public mapping construction of runtime economics is disabled to prevent caller-supplied accounting becoming truth.

## Safety boundary

This PR remains offline and sender-free:

- no live trading;
- no signer/private-key loading;
- no provider/RPC/Jito/Helius/Jupiter/MarginFi/Kamino network calls;
- no transaction construction, simulation execution or submission;
- no production registry mutation;
- no claim that full MPR-04 is complete.

## Focused verification

```bash
python -m py_compile \
  src/mpr04_protocol_bound_economics.py \
  tests/test_mpr04_protocol_bound_economics.py
python -m pytest -q tests/test_mpr04_protocol_bound_economics.py
```

## Remaining MPR-04 work

This is the first MPR-04 slice, not the full vertical. Remaining work must wire this contract into the installed MPR-01/MPR-02 runtime authority and replace parallel PR-197/198/199 proof islands with one atomic path:

```text
capital reservation → planner → compiler → exact simulation raw state → decoder-owned repayment/PnL → reconciliation
```

The full MPR-04 definition of done still requires real rooted MarginFi/Kamino ProgramData/reserve/mint bytes, canonical ATA PDA derivation, Token-2022 extension policy, wSOL lifecycle/lamport invariants and golden vectors flowing from raw rooted accounts to reconciliation without caller-supplied deltas or profit.
