# PR-028 — MarginFi binary decoding and instruction conformance

## Status

This change replaces the synthetic JSON account format with source-derived
binary layouts for the pinned MarginFi / Project Zero deployment. It remains
**quarantined and shadow-only** until both conditions are met:

1. PR-027 is merged and its provenance registry points to the same program id
   and upstream commit.
2. `tests/providers/test_marginfi_readonly_optin.py` passes against operator
   supplied, read-only mainnet RPC evidence.

No signer, sender, permit, Jito path, or live-mode switch is added.

## Pinned source

The packaged contract is `src/resources/marginfi_pr028.json`.

- repository: `0dotxyz/marginfi-v2`
- commit: `d4c70c84f8a9692405a2c32cbd7095bb1fe3f428`
- program: `MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA`

The account sizes, offsets, discriminators, flags, and instruction account
orders are derived from the exact `type-crate` and program sources at that
commit. The loader also reads `docs/contracts/marginfi_mainnet.json` when it is
present. Both pins must agree on program id and source commit, so merging
PR-027 cannot silently change the protocol interpreted by PR-028.

## Safety invariants

- Group, MarginFi account, and Bank data must have the exact pinned byte length.
- Owner and discriminator mismatches fail closed.
- Margin account balances must be in the upstream-required bytewise order.
- Active protocol pause, protected account flags, and a non-operational target
  bank reject the candidate.
- Target vault liquidity is read from the SPL/Token-2022 account, not invented
  in a fixture.
- Follow-up reads use `minContextSlot` and cannot predate the first snapshot.
- The target bank may not already be active because `repay_all=Some(true)` must
  not alter a pre-existing position.
- Origination fee is decoded as signed little-endian I80F48 and rounded upward
  using integer arithmetic for the conservative repayment bound.
- Token-2022 banks include the mint as the first remaining account.
- `start_flashloan` includes the Instructions sysvar.
- Borrow, repay, and end account metas follow the pinned upstream structs.
- Repay encodes Borsh `Option<bool>` as `Some(true)`.
- The provider only returns instructions and immutable evidence. It cannot
  sign or submit.

## Offline verification

```bash
python -m pytest tests/providers/test_marginfi_provider.py -q
python -m compileall -q src/providers/marginfi tests/providers
```

The synthetic JSON discriminator fixture is included only as a negative test
and must be rejected.

## Opt-in mainnet verification

Set:

```bash
export MARGINFI_READONLY_RPC_URL='https://...'
export MARGINFI_READONLY_GROUP='...'
export MARGINFI_READONLY_MARGIN_ACCOUNT='...'
export MARGINFI_READONLY_AUTHORITY='...'
export MARGINFI_READONLY_BANK='...'
export MARGINFI_READONLY_SYMBOL='USDC'
export MARGINFI_READONLY_AMOUNT='1'
```

Then run:

```bash
python -m pytest tests/providers/test_marginfi_readonly_optin.py -m live -q
```

A skipped test is not conformance evidence. The PR must stay draft/quarantined
until a real run passes and its redacted slot, pin hash, and fixture hashes are
attached for human review.
