# PR-114 semantic instruction firewall

PR-114 adds a sender-free semantic firewall for untrusted provider instruction
artifacts before any signing, sender, Jito, or live-execution boundary can see
them.

## Why Program ID allowlists are not enough

A Program ID allowlist proves only which program will receive an instruction. It
does not prove that the instruction is semantically safe. Allowlisted programs can
still encode authority changes, delegate approvals, account closes, arbitrary
system transfers, mint/burn paths, or Token-2022 extension behavior.

## Scope

The firewall is a planning boundary. It validates provider-owned Jupiter
instruction buckets:

- setup
- other
- swap
- cleanup

It returns positive validation evidence for accepted instructions and typed
fail-closed errors for rejected ones.

## Current fail-closed checks

- provider-owned compute/tip instructions are rejected;
- undeclared signers are rejected;
- writable payer or wallet-owned accounts are rejected;
- SPL Token approve/set-authority/mint/burn/close families are rejected;
- Token-2022 is rejected until an explicit extension policy exists;
- System Program transfer and non-explicit system tags are rejected;
- ATA data shape is guarded;
- pinned Jupiter programs are classified as pinned, not generally trusted.

## Non-goals

This PR does not enable live trading, signing, transaction sending, RPC/Jito
submission, MarginFi execution changes, or automatic provider admission. Full
Token-2022 extension matrices and route-specific Jupiter discriminator policies
should be layered on top of this typed boundary in later PRs.
