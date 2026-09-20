# MPR-2617 — Direct venue execution expansion

Status: `NEW_PROPOSED_EXTENSION`.

## Predecessor / ownership preflight

- Main observed at implementation start: `d23f82e20d10345926742352739b1a6ca3f7a859` (merge of MPR-2611 / PR #482).
- No `2616` branch was returned by repository branch search; status remains `RESERVED_PREDECESSOR_UNOBSERVED`.
- No `2617` branch existed before this work.
- `AGENTS.md` was not present at repository root on the observed main.
- MPR-2617 does not recreate runtime, provider governance, capital, human control, compiler, exact simulator, signer/submission, canary, finalized economics or release qualification.

## Base route preserved

Jupiter/Jupiter remains the existing first-v1 production-target route. MPR-2617 adds only an exact direct-venue capability/evidence boundary; it does not modify the Jupiter router.

## Orca first target

Current primary-source review (2026-09-09):

- official repository: `https://github.com/orca-so/whirlpools`;
- reviewed source head: `408c945fef4c49ab70def4303377cfaf8f0f3c99`;
- official deployed Whirlpools program: `whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc`;
- current source license is the post-2025-02-26 Orca License, not Apache-2.0-only.

No Orca SDK/core source is copied by this PR. The module independently models exact evidence and deliberately requires `license_review_approved=true` before an Orca proof can become `OFFLINE_VERIFIED`. Commercial source/SDK use therefore remains a review/consent boundary rather than being silently assumed.

## Implemented boundary

`src/direct_venue/mpr2617.py` adds:

- exact non-wildcard `VenueCapability` identity;
- explicit states: research, offline-verified, shadow-qualified, canary-eligible, production-qualified, blocked, revoked;
- program/pool/mint/direction/deployment/layout/math/evidence binding;
- rooted account evidence for pool/vault/tick-array state;
- Orca source/program/root/generation/local-vs-reference quote/instruction-account checks;
- Token extension fail-closed checks;
- exact route-leg capability hash binding;
- explicit route-combination admission rather than N×N auto-enablement;
- asset continuity and `next.amount_in <= previous.guaranteed_min_out` conservation;
- immutable route hash;
- `live_enabled=false` in every result.

This is a consumer/gate only. It has no network client, no transaction builder, no signer and no sender.

## Exact venue matrix at this head

| Venue | Status | Notes |
|---|---|---|
| Jupiter/Jupiter | existing base unchanged | owned by predecessor route stack |
| Orca Whirlpools | IMPLEMENTED / offline gate | exact pool evidence required; no pool is claimed qualified from fixtures |
| Raydium CPMM | BLOCKED_EXTERNAL / future | family reserved, no executable capability |
| Raydium CLMM | BLOCKED_EXTERNAL / future | family reserved, no executable capability |
| Meteora DLMM | BLOCKED_EXTERNAL / future | `consumedInAmount` semantics still require current vectors |
| Phoenix | existing shadow-only seams reused | no live promotion |
| OpenBook V2 | existing shadow-only seams reused | no live promotion |

## Why no concrete Orca pool is called qualified

The task requires rooted current pool/tick-array account bytes, independent SDK/core differential vectors, exact swap bytes/account order, governed provider receipt, final canonical compile/firewall/simulation, lender repayment and real venue-specific shadow evidence. This session has no approved rooted RPC evidence artifact or commercial Orca source/SDK license approval. Fabricating a pool qualification would violate the task's fail-closed evidence rules.

The code therefore makes that missing evidence explicit instead of using a historical pool address or fixture as production permission.

## Parallel safety

Legacy `src/ingest/amm_math.py`, `src/ingest/tx_builder.py`, `src/config/addresses.py` and `src/legacy_arb_bot.py` are not promoted. Existing `src/providers/orderbook` remains shadow-only and unchanged.

## Remaining before direct canary

1. Approved current rooted Orca pool/vault/tick-array evidence for one exact direction.
2. Independent current quote and instruction vectors without copying restricted upstream source into this repository.
3. Commercial/license approval as applicable.
4. Canonical compiler/firewall/exact simulation integration on the accepted predecessor head.
5. Lender repayment + conservative economic proof.
6. Installed sender-free venue-specific real shadow campaign.
7. Separate route-combination qualification for Jupiter→Orca, Orca→Jupiter and Orca→Orca.

No trading key, signing, submission, funding, capital increase, direct-live activation or auto-merge is part of MPR-2617.
