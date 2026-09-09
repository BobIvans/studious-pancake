# MPR-2615 controlled multi-lender expansion status

MPR-2615 is a **NEW_PROPOSED_EXTENSION**. It is not a recovered historical 2601–2612 task.

## Preflight

- base used for this checkpoint: `main@d23f82e20d10345926742352739b1a6ca3f7a859` (merged MPR-2611 / PR #482)
- no `2614` branch was observed during this checkpoint; status remains `RESERVED_PREDECESSOR_UNOBSERVED`
- the first v1 profile remains `circular_arbitrage+marginfi+jupiter`
- the first expansion target is `circular_arbitrage+kamino-klend+jupiter`
- Save scopes remain default-off and pool-specific

## Implemented in this checkpoint

- one fail-closed expansion capability contract layered on the existing packaged Kamino supported-combination resource;
- explicit lifecycle states from research through production-qualified/revoked;
- no wildcard market/reserve/combination admission;
- candidate identity binds lender capability + exact combination + final message + final simulation;
- exact-integer lender repayment/fee obligation checks reject bool/float/coercion;
- selection excludes unqualified lenders even when their gross edge is better;
- lender switching requires a fresh pre-effect candidate and is forbidden after effect issuance;
- Save Main Pool and permissionless pools are distinct disabled scopes.

## External truth intentionally not fabricated

The Kamino `combinations` array remains empty. Current official KLend source/SDK observations are useful provenance hints, but this checkpoint did not obtain the release-bound deployed market/reserve/mint/oracle/vault bytes required by the task. Therefore Kamino remains `research`, not executable.

Primary-source observations rechecked on 2026-09-09:

- the current Kamino KLend SDK generated program identity is `KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD`;
- current Kamino KLend NOTICE uses Business Source License terms, so upstream source is not copied into this repository;
- Save distinguishes its Main Pool from permissionless pools and exposes pool-specific warnings, so no generic `save=true` capability exists.

These observations are not treated as deployed qualification evidence.

## Safety

No private key, signing, submission, funding, live lender activation, capital increase, or auto-merge is part of this checkpoint.
