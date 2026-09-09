# MPR-2619 implementation status

This branch implements the first fail-closed liquidation strategy expansion checkpoint from the supplied MPR-2619 pack.

## Implemented

- keeps the existing `src.liquidation` package fixture-only and quarantined;
- adds a separate MarginFi-classic-only qualification contract;
- rejects receivership, deleverage and Kamino liquidation at this boundary;
- rejects the current placeholder financing program `marginfi_flashloan_provider_pr009`;
- rejects generic `route` unwind instructions and hard-coded `end_index:` markers;
- requires explicit lender, unwind, exact-ABI, circuit-breaker, raw simulation decoder and economic-ledger evidence before the checkpoint can become `VERIFIED_OFFLINE`;
- adds an explicit instruction firewall over qualified programs and instruction names;
- replaces caller-trusted simulation booleans at the qualification boundary with a raw-evidence contract requiring target debt/collateral state changes, exact flash principal + fee repayment, complete economics and positive realized PnL.

## Deliberately not implemented

This checkpoint does not claim current MarginFi classic ABI qualification. It does not encode or submit `start_liquidation`, `liquidate` or `end_liquidation`; it does not add a live signer path; it does not enable liquidation through config; it does not qualify MarginFi receivership/deleverage or Kamino liquidation; it does not treat synthetic replay as production evidence.

Those remain blocked until current deployed protocol vectors, financing/unwind combinations, exact final simulation decoding and strategy-specific real shadow evidence are independently proven.
