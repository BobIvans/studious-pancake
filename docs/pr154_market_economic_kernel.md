# PR-154 — Market, MarginFi state and exact economic decision kernel gate

This starts the renamed snapshot-9 PR-154 scope as a low-conflict additive
contract. It does not call providers, RPC, Jupiter, MarginFi, signer or sender.
It defines the evidence boundary that a later integration must satisfy before an
exact candidate can proceed toward canonical transaction proof.

## Implemented slice

- Adds `src/market_economic_kernel_pr154.py`.
- Adds `tests/test_pr154_market_economic_kernel.py`.
- Requires exact first-leg output to equal second-leg input.
- Requires final exact route rebuild hashes.
- Requires attested route program IDs.
- Requires deterministic opportunity identity and persistent dedup/cooldown.
- Requires final-build quota reservation and shared limiter evidence.
- Requires complete reviewed MarginFi IDL/account/instruction/RPC/group-bank-vault-oracle evidence.
- Rejects mixed-slot MarginFi state.
- Requires asset/mint/rent/transfer-fee/authority evidence.
- Requires optional LST policy to be disabled or reviewed.
- Rejects monotonic binary-search sizing assumptions.
- Requires integer base-unit cost ledger and exact flash repayment.
- Requires wallet SOL reservation for fees/tip/rent.
- Requires explicit ATA/wSOL lifecycle policy.
- Returns `NO_TRADE` only when otherwise complete evidence is below profit threshold.

## Safety / non-goals

- No trading.
- No paper/live execution enablement.
- No signer or sender path.
- No RPC/Jito/Helius/MarginFi/Jupiter call.
- No active runtime wiring.

`sender_submission_allowed` and `live_claim_allowed` remain false.

## Suggested verification

```bash
python -m pytest tests/test_pr154_market_economic_kernel.py -q
python scripts/verify_repo.py --skip-dependency-audit
```

## Follow-up integration

Later PR-154 integration can feed this contract from real discovery, MarginFi,
asset registry, quota, sizing, reservation and fee-ledger components once
PR-152/153 contracts are stable.
