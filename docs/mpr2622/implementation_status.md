# MPR-2622 stable peg / CLMM-DLMM qualification — implementation checkpoint

Base observed at implementation: `main@d23f82e20d10345926742352739b1a6ca3f7a859` after MPR-2602…2611 merged.

Ownership recheck:
- MPR-2619 branch owns liquidation under `src/liquidation/**`; no overlap.
- MPR-2621 branch currently points at main with no changes; its reserved LST NAV scope is not implemented here.
- no MPR-2620 or MPR-2622 branch was present at branch creation.

Implemented in this checkpoint:
- isolated `src/strategies/stable_peg` package;
- mint/program/decimal/reference/pool evidence models with non-bool integer validation;
- CLMM tick-array and DLMM bin-array presence gates;
- exact integer conservative tick/bin band traversal with floor output and ceil fee rounding;
- amount-coupled content-addressed stable-peg candidates;
- hard-bounded integer sizing optimizer with healthy `NO_TRADE` behavior;
- Pyth-style integer price/exponent freshness/confidence/disagreement policy;
- immutable qualification artifact that can only report `VERIFIED_OFFLINE`, `RECORDED_OFFLINE`, or `BLOCKED_INTEGRATION` and always keeps live/release/production capabilities false;
- architecture regression denying signer/sender/direct-network/legacy-ingest imports.

Explicit residual blockers:
- venue-specific Orca/Raydium account decoders and official golden vectors;
- Meteora DLMM raw bin decoder and dynamic-fee deployed conformance;
- exact current program/deployment evidence from rooted registry;
- direct binding to accepted compiler/instruction-firewall/final exact simulation and durable capital authority;
- full A01-A80 evidence mapping, wheel/reachability registration if required by canonical architecture owner, mutation witnesses, full repository CI and installed artifact qualification;
- real shadow/deployed evidence remains owned by downstream authorities.

This PR is sender-free and does not claim profitability, deployed conformance, live readiness, release readiness, or production readiness.
