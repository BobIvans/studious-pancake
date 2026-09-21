# MEGA8-04 — Formal assurance, evidence trust, exact multichain and post-150 release

Base at branch creation: `main@04480fa25d1117e9d20e7fe8caad23b16cd5ef4a`.

MEGA8-04 covers roadmap **PR-209..PR-222 / NF-585..NF-640**. It is an
offline/default-off assurance and research closure over current canonical owners.
It does not create a second runtime, signer, sender, economic ledger, multichain
release authority, or production promotion path.

## Current-head reuse

- security/parser/supply-chain: `src/security/*`;
- exact simulation/execution lifecycle: `src/execution/*` and `src/submission/*`;
- HA/recovery: `src/ha_dr/mpr2616.py` and existing durability owners;
- release/independent assurance: `src/release_gate/*`;
- isolated signer semantics: `isolated_signer_service/.../mpr2608.py`;
- EVM/Sui execution models: `src/multichain/*`;
- sender-free multichain strategy qualification: `src/cross_chain/agg12.py`.

`src/mega8_04.py` is an integration facade for the new NF identities. Existing
canonical modules remain authoritative for production behavior.

## Child closure

| Child | NF | Code disposition | Operational truth |
|---|---|---|---|
| PR-209 VERIFY-01 | NF-585..588 | offline property/invariant contracts | external campaign evidence not claimed |
| PR-210 VERIFY-02 | NF-589..592 | offline mutation/fuzz contracts | coverage-guided campaign not claimed |
| PR-211 VERIFY-03 | NF-593..596 | executable state-machine model checking | external TLA+/Apalache run optional/not claimed |
| PR-212 SIM-04 | NF-597..600 | exact multi-engine quorum evidence | real simulator fleet qualification remains |
| PR-213 CHAOS-01 | NF-601..604 | declarative fault/recovery evidence | deployed chaos drill remains |
| PR-214 SUPPLY-01 | NF-605..608 | deterministic CycloneDX-style SBOM/repro/license/provenance gates | external SLSA publication remains |
| PR-215 EVIDENCE-02 | NF-609..612 | append-only signature-evidence hash chain and Merkle roots | external signing/publication remains |
| PR-216 SIGNER-02 | NF-613..616 | metadata/ceremony/rotation/recovery contracts | real HSM/KMS remains default-off |
| PR-217 EVM-04 | NF-617..620 | exact integer research adapter/calldata/differential boundary | protocol deployments/vectors remain unqualified |
| PR-218 EVM-05 | NF-621..624 | callback settlement research qualification | fork/deployment qualification remains |
| PR-219 SUI-02 | NF-625..628 | object frame/locks/PTB-delta research contracts | deployed PTB campaign remains |
| PR-220 XCHAIN-01 | NF-629..632 | rights/finality/inventory/reconciliation research | bridge/custody evidence remains |
| PR-221 DSL-01 | NF-633..636 | verified primitive DSL and capability sandbox | plugin runtime remains research-only |
| PR-222 RELEASE-02 | NF-637..640 | append-only post-150 audit/campaign/verdict/cycle | release claim remains false |

Each child has a machine-readable artifact under
`release_artifacts/mega8/MEGA8-04/`.

## Security/effect boundary

The MEGA8-04 facade performs no RPC/HTTP submission, private-key access, signing,
account funding, bridge transfer, live activation, remote service mutation, or
automatic capital increase. EVM, Sui, cross-chain, HSM and plugin surfaces are
research/default-off unless separately admitted by their existing authorities.

Unknown state, simulator disagreement, semantic mutation, privilege escalation,
missing finality, incomplete post-150 coverage, or unsafe plugin capability
fails closed.

## PR-222 release semantics

PR-222 is implemented as an **honest audit**, not as an automatic release. It
requires one evidence-backed row for every PR-151..221 and keeps
`release_claim_allowed=false`, `production_ready=false`, and
`live_enabled=false` in this closure. Research-only/deferred/blocked scope is
preserved explicitly rather than relabeled as production evidence.

## Verification

- `python scripts/verify_mega8_04.py --json`;
- `pytest -q tests/test_mega8_04.py`;
- focused canonical-owner regressions for multichain, isolated signer and
  supply-chain/security;
- repository CI and Release authority on the exact current PR head.

## Rollback

Revert the MEGA8-04 merge or stop consuming its integration-facade outputs.
Existing canonical owners remain unchanged. Preserve child evidence and any
append-only incident/qualification records for audit and recovery.
