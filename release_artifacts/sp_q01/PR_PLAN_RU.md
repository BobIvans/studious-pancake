# SP-Q01 PR plan

## One confirmed blocker

Harden the existing installed financing resolver so a boolean `qualified=true`
cannot substitute for protocol admission evidence.

## Minimal change

- add one pure admission-receipt validator;
- upgrade the installed financing manifest to v2;
- bind PRIMARY to Jupiter Lend and RENT to Slumlord source/program/account
  identities;
- require build/programdata/account hashes, rooted freshness, expiry and manual
  review;
- require the existing `evidence_sha256` to equal the structured receipt hash;
- keep MarginFi fail-closed;
- add regression tests and a dedicated verifier.

## Rollback

Revert this PR. That restores the previous weaker manifest semantics but does
not alter lifecycle, capital, signer, sender, wallet, network, or historical
evidence state.

## Non-goals

No RPC acquisition, no on-chain mutation, no live qualification claim, no
MarginFi unpause, no new planner/runtime/admission registry.
