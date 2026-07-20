# PR-055 — MarginFi authoritative source and deployment conformance

## Purpose

This PR starts the PR-055 remediation item without changing the active planner,
compiler, simulator, signer, sender, or live admission path. It resolves the
apparent source-repository conflict and adds a fail-closed promotion gate.

## Source identity resolution

The current MarginFi documentation links to:

- `https://github.com/mrgnlabs/marginfi-v2`

GitHub resolves that URL to:

- `https://github.com/0dotxyz/marginfi-v2`

They are aliases for the same repository, not two independently maintained
sources. The existing PR-028 source commit
`d4c70c84f8a9692405a2c32cbd7095bb1fe3f428` is the merge of the 0.1.9
consolidated update. Comparison with reviewed head
`72c1680f119152d7d83972523d1706bc73e50cc9` shows only documentation changes in
`SECURITY.md` and `guides/ADMIN/DEPLOY_GUIDE.md`; no protocol source/layout file
changed after the PR-028 pin in that reviewed range.

This resolves repository identity, but it does **not** prove that the deployed
mainnet executable equals a locally rebuilt artifact.

## Deployment evidence

The official deploy guide records:

- program: `MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA`;
- mainnet release 0.1.9 deployment date: 14 July 2026;
- published hash prefix: `26dda5e`;
- verification through `solana-verify verify-from-repo`;
- deployed executable inspection through `solana-verify get-program-hash`.

A prefix is diagnostic metadata only. PR-055 requires the complete deployed
program hash and complete reproducible-build hash to match byte-for-byte before
execution conformance can become true.

## New gate

`src.providers.marginfi.deployment_conformance` validates the packaged
`src/resources/marginfi_pr055.json` evidence manifest. Promotion requires all
of the following independent evidence families:

1. exact source/repository identity and pinned commit;
2. matching full deployed and reproducible-build hashes;
3. canonical on-chain Program Metadata IDL hash;
4. SDK-generated account and instruction golden-vector hashes;
5. read-only mainnet group, account and bank relationship evidence;
6. current flash-loan metas, pause/fee behavior and Token-2022 evidence;
7. explicit human review and promotion flag.

The packaged manifest intentionally leaves unavailable evidence as `null` or
`false`. Therefore the current result is blocked and live remains denied.

## Verification

```bash
python -m pytest tests/providers/test_marginfi_pr055_conformance.py -q
python -m compileall -q \
  src/providers/marginfi/deployment_conformance.py \
  tests/providers/test_marginfi_pr055_conformance.py
```

The focused tests prove that a hash prefix, repository alias, human flag, or
local fixture cannot independently unlock execution.

## Follow-up required to complete PR-055

This first slice does not fabricate online evidence. Completion still requires
an operator-controlled read-only RPC and reproducible build environment to:

- capture the full deployed executable hash;
- rebuild the pinned commit and capture the full build hash;
- fetch and hash the canonical on-chain IDL;
- generate SDK golden account/instruction vectors;
- verify real group/account/bank relationships at a pinned context slot;
- review current flash-loan metas, fees, pause semantics and Token-2022 paths;
- attach redacted evidence hashes and human approval.

Until those artifacts are reviewed, `execution_conformance_verified` must remain
`false`.
