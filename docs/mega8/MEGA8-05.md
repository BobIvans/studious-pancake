# MEGA8-05 — Autonomous R&D, experiment governance and statistical market intelligence

## Scope

This branch implements the **offline/default-off code slice** for roadmap
children **PR-239..PR-254** and **NF-641..NF-704**. The package lives under
`src/research/mega8_05/` and deliberately does not become a runtime, signer,
sender, settlement authority, or capital authority.

Branch creation base: `main@04480fa25d1117e9d20e7fe8caad23b16cd5ef4a`.

## Dependency truth at branch creation

The roadmap names MEGA8-01, MEGA8-02, MEGA8-03 and MEGA8-04 as prerequisites.
At branch creation, `codex/mega8-01-151-162` and
`codex/mega8-02-163-185` were observed as branches but were not merged into
`main`. After synchronizing with `main@e14d7f2e0d90dee2dce573761baba185feace5ea`,
the exact prerequisite state was refreshed: MEGA8-02 is open as PR #523,
MEGA8-03 as PR #521 and MEGA8-04 as PR #522; MEGA8-01 still has only an
observed branch. None is merged into current main. Therefore this PR does
**not** claim operational completion. It is reviewable as an independent,
sender-free research code slice while dependency readiness remains explicit in
the coverage artifact.

If those prerequisites merge before this PR, the branch must be synchronized
with current `main`, the dependency evidence refreshed, and affected checks
rerun before merge.

## Child ownership

| Child | NF | Canonical owner in this PR | Status |
|---|---|---|---|
| PR-239 / UPSTREAM-03 | NF-641..644 | `pr239_upstream.py` | IMPLEMENTED_OFFLINE |
| PR-240 / CODEGEN-01 | NF-645..648 | `pr240_codegen.py` | IMPLEMENTED_OFFLINE |
| PR-241 / ADAPTER-SDK-01 | NF-649..652 | `pr241_adapter_sdk.py` | IMPLEMENTED_OFFLINE |
| PR-242 / DISCOVERY-02 | NF-653..656 | `pr242_discovery.py` | IMPLEMENTED_OFFLINE |
| PR-243 / SEMANTICS-01 | NF-657..660 | `pr243_semantics.py` | IMPLEMENTED_OFFLINE |
| PR-244 / LICENSE-02 | NF-661..664 | `pr244_license.py` | IMPLEMENTED_OFFLINE |
| PR-245 / EXPERIMENT-01 | NF-665..668 | `pr245_preregistration.py` | IMPLEMENTED_OFFLINE |
| PR-246 / EXPERIMENT-02 | NF-669..672 | `pr246_multiple_testing.py` | IMPLEMENTED_OFFLINE |
| PR-247 / LABEL-01 | NF-673..676 | `pr247_labels.py` | IMPLEMENTED_OFFLINE |
| PR-248 / ENTITY-01 | NF-677..680 | `pr248_entity.py` | IMPLEMENTED_OFFLINE |
| PR-249 / FACTOR-01 | NF-681..684 | `pr249_factors.py` | IMPLEMENTED_OFFLINE |
| PR-250 / STATARB-01 | NF-685..688 | `pr250_stat_arb.py` | IMPLEMENTED_OFFLINE |
| PR-251 / REGIME-01 | NF-689..692 | `pr251_regimes.py` | IMPLEMENTED_OFFLINE |
| PR-252 / LEADLAG-01 | NF-693..696 | `pr252_leadlag.py` | IMPLEMENTED_OFFLINE |
| PR-253 / FLOW-01 | NF-697..700 | `pr253_flow.py` | IMPLEMENTED_OFFLINE |
| PR-254 / SCAM-01 | NF-701..704 | `pr254_scam.py` | IMPLEMENTED_OFFLINE |

## Architecture and safety

The package consumes already captured metadata, fixtures, observations, or
numeric sequences. It performs no provider discovery calls itself. This is
intentional: external repositories, schemas and chain data are untrusted inputs
until captured and admitted by existing repository authorities.

The following invariants are hard-coded and regression-tested:

- generated code is returned as text and is never executed by the codegen
  validator;
- generated skeletons declare `SIGNING_ALLOWED = False` and
  `SUBMISSION_ALLOWED = False`;
- unknown deployments become quarantine evidence, not strategy admission;
- inferred CPI/account/resource semantics remain hypotheses until fixtures and
  invariants validate them;
- unknown or unsupported source-license evidence prevents PORT/VENDOR copying;
- preregistration identity changes when the hypothesis/plan/cutoff changes;
- multiple-testing correction and executable/economic evidence are required
  before a discovery claim can pass its research gate;
- unsent/skipped observations are not silently relabelled as landed outcomes;
- ticker symbols alone never merge asset identities;
- factor, lead-lag and public-flow outputs are research/ranking inputs, not
  execution authority;
- statistical arbitrage remains a separate non-atomic research/risk domain and
  cannot inherit atomic tiny-live permissions;
- an unknown regime falls back to `no-trade`;
- missing liquidity/behavior data is `UNKNOWN`, never silently labelled a rug;
- dynamic authority, liquidity, behavior or extension risk revokes admission
  fail-closed.

## External source / license boundary

No external source file is copied by this PR. Candidate upstreams mentioned by
the roadmap remain **REFERENCE/WRAP/TOOL candidates** until an immutable
commit/tag, exact file/symbol/test dependency closure, file hashes, license and
required notices are independently recorded.

`pr244_license.py` is an engineering policy gate, not legal advice. Its
allowlist is deliberately narrow. Unknown/non-allowlisted licenses force
`REFERENCE_ONLY` for source-copy modes.

## Statistical boundary

The compact pure-Python statistical helpers are intentionally conservative
research primitives. They do not claim that a lightweight candidate score is
a formal cointegration test, causal proof, profitability proof, or production
model. Formal/third-party statistical packages may be evaluated later through
the upstream/license/adapter gates, with pinned versions and differential
evidence.

## Verification

Focused commands:

```text
python -m compileall -q src/research/mega8_05 scripts/verify_mega8_05.py
python scripts/verify_mega8_05.py --json
python -m pytest tests/test_mega8_05_research_factory.py -q
```

The structural verifier requires:

- exactly 16 child owners;
- exactly 64 unique primary NF, NF-641..NF-704;
- four exact public functions per child;
- no effectful network/subprocess/Solana imports in child modules;
- no signer/submission/live flags;
- explicit dependency and external-evidence blockers.

Repository CI and Release authority remain authoritative.

## Rollback

Because this slice is not wired to live execution, rollback is removal or
disablement of the research package/workflow while retaining coverage/evidence
records for audit. No started transaction or capital operation is created by
this package.

## Honest status

- implementation: **IMPLEMENTED_OFFLINE**
- operational: **BLOCKED_DEPENDENCIES**
- activation: **DEFAULT_OFF**
- signing/submission/live trading: **false**
- automatic capital increase: **false**
- production-ready claim: **false**
