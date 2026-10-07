# RentSponsorPlanner

## Goal

Choose the cheapest safe account/rent funding mode per Solana execution plan.

The planner must not assume every route needs a newly funded persistent ATA.

## Modes

```text
EXISTING_ACCOUNT
PROVIDER_SPONSOR
SLUMLORD_EPHEMERAL
LOCAL_PERSISTENT
ROUTER_PAYER
NOT_SUPPORTED
```

## Decision order

1. Reuse a qualified existing token account when possible.
2. If the quote/build provider supports a separate sponsor/payer, evaluate provider sponsorship.
3. If all newly-created intermediate token accounts can be emptied and closed in the same transaction, evaluate Slumlord.
4. If the output account must remain alive, fund it persistently.
5. Reject the route if rent/fee economics destroy the edge.

## 0x Solana

0x `/solana/swap-instructions` supports a `sponsor` field.

The API documents the sponsor as transaction fee payer and rent payer for a fully-sponsored swap. The taker still signs.

When a taker-owned token account is created using sponsorship, the sponsor can retain close authority and reclaim rent once the account is empty.

Integration requirements:
- preserve sponsor signer requirement;
- locally inspect all returned instructions;
- do not assume a custom recipient/fee-recipient account is refundable;
- include sponsor rent economics in normalized quote/build evidence.

## Titan

Titan V3 supports a separate `payer` for SOL-denominated costs such as network fees and ATA rent. That payer must co-sign.

Treat Titan payer as a distinct `PROVIDER_SPONSOR` / external payer mode, not as free money.

## Slumlord

Use `SLUMLORD_EPHEMERAL` only when every Slumlord-funded temporary account can be closed before repayment.

Slumlord cannot permanently fund the final non-empty ATA.

## Local persistent ATA

Required when:
- final output representation must remain in a token account;
- token balance is non-zero at transaction end;
- account close authority cannot safely be assigned/recovered;
- Slumlord/provider-sponsor constraints do not compose with route/flash-loan bookends.

## Economics

Record:
- account rent requirement;
- sponsor cost;
- refundable amount;
- unrecoverable amount;
- extra instruction bytes/CU;
- extra signer count;
- account-lock cost;
- failure/landing penalty.

Rank net route economics after these costs.

## Acceptance

The system may truthfully claim:

> For each Solana route, RentSponsorPlanner chooses among reuse, provider sponsorship, Slumlord ephemeral rent financing and persistent local funding while preserving exact account semantics.

It must never claim:

> Every Solana pair can use an ATA for free.
