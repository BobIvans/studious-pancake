# R-02: authentic partial observations, capital readers BLOCKED

Assignment: PR #583 at `e059b1551dd575e25f54979fbe73316bbd0ce316`.
Base: main `103c13795f1d2ac1fa88cf02bba1e9bb2e2477cf`.
R-01 passed; its separate verification PR is #584 and remains unmerged.

Read the entire assignment's `offline/` bundle locally from a Git archive.
`offline/verify_bundle.py` passed: 27 disabled candidate IDs, 17 signatures,
10 source pins. Those 27 options remain a future research/cost-selection catalog;
none were enabled, no R-07 work or callback contract deployment was attempted.

## Real results and stop conditions

| Provider | Actual observation | Why no qualified capital snapshot exists |
| --- | --- | --- |
| Jupiter Lend | Finalized slot 454401538: admin PDA owner/layout match the existing pinned decoder; status true, fee 0, inactive, active amount 0. Program account also exists. | No local pinned full liquidity-reserve/cap decoder, reviewed mint-resource binding, independently rooted quorum, or wallet ATA/setup cost proof. Admin fee zero does not prove capacity or zero upfront cost. |
| Kamino | Program account at the same slot is executable under the upgradeable loader. | Program presence is not deployed bytecode attestation. Local fixture JSON decoding and v1.23 review cannot validate the required v1.25 reserve, SDK 13.0.2, flash fees, limits or oracle state. |
| NAVI | Initial GraphQL chain checkpoint 331514367 was received; a later governed checkpoint request timed out. Both results are preserved. | Neither result is NAVI pool state. No local pinned modular `@naviprotocol/lending` SDK/current package, pool or decimal bindings; legacy SDK/interface summaries cannot supply the missing ABI. |
| Project 0 | No wallet-specific request executed. | Public addresses of an existing account and its authority were not supplied; existence is unknown, not proven absent. Current `@0dotxyz/p0-ts-sdk` 2.8+ is also unavailable locally. No account initialization attempted. |

Per the assignment's stop rule, missing layouts were not invented or recovered
from website documentation. **Four qualified live readers were not delivered;
R-02 is BLOCKED, with zero qualified edges.** Jupiter's capital-graph integration
gap remains open until reserve/fee/cap/source evidence is available. This PR
delivers reproducible prerequisite observations and stop receipts, not a new
graph, lender adapter, capital selector, transaction engine or execution permit.

## Evidence, replay and owners

`CAPTURE.json` records requests, public endpoint profiles/generations, timestamps,
responses and hashes. `INITIAL_CONNECTIVITY.json` preserves the first diagnostic
run unchanged, including successful Sui checkpoint and earlier Jupiter admin.
`RECEIPT.json` binds capture hashes, assignment files/pins and provider blockers.
These public smoke captures have no independent quorum or trusted signature;
hash consistency does not establish authenticity against a malicious rewriter.

`capture_prerequisites.py` reuses existing public QPR profiles, platform TLS/proxy
transport, `ProviderGovernance` physical admission/quotas, native collector,
DIN-02 GraphQL profile/query, and the existing Jupiter admin decoder. Each run
makes at most two Solana requests and one GraphQL request, no automatic retry,
zero spend authorization; it never issues protocol account creation or transaction
methods. A fresh evidence filename is required; existing files are not overwritten.
It is a smoke/prerequisite diagnostic, not a qualification campaign. The default
public profile remains smoke-only; no credential or admission promotion occurs.

From the repository root with the prepared Python 3.13 environment:

```bash
python docs/verification/r02-2026-10-08/capture_prerequisites.py --replay docs/verification/r02-2026-10-08/CAPTURE.json
# Optional new read-only diagnostic; use an unused output path:
python docs/verification/r02-2026-10-08/capture_prerequisites.py --output /tmp/r02-new-capture.json
python -m pytest tests/test_r02_prerequisite_capture.py tests/test_dynamic_flash_capital.py tests/lending/test_agg03_financing_ports.py tests/lending/test_kamino_pr050.py tests/lending/test_kamino_pr095_real_conformance.py -m 'not live and not manual' --disable-socket --allow-unix-socket -q
```

Replay makes no network requests and does not refresh historical observations.
Eight new replay tests cover deterministic decoding, tampering, owner/genesis/
finality mismatch, execution flags and unavailable network; 35 focused tests
passed. The full canonical verifier is recorded separately in the receipt.
Existing resolver, source admission, Dynamic Universe and capital-graph owners
are unchanged; no new provider or weakened production gate is introduced.

## Inputs required to resume

Supply reviewed pinned liquidity/reserve decoders and deployment/resource bindings
for Jupiter and Kamino, a current modular NAVI SDK/package pin and reviewed pool
bindings, and the public addresses of an existing P0 account and its authority
plus the current SDK pin. Then use admitted independent rooted sources and retain
actual protocol captures/replay. Account/ATA/gas costs stay UNKNOWN until proven;
no private key is requested and no new account may be created under R-02.

No signing, sending, flash borrowing, token account creation, funds spending,
provider enabling, release/paper gate change or production promotion occurred.
