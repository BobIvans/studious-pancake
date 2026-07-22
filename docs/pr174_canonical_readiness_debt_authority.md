# PR-174 — Canonical readiness and debt-authority consolidation

This PR starts PR-174 as the canonical readiness/debt authority layer.

Snapshot `(11)` shows that the repository has become more honest and more fail-closed, but it still has multiple parallel truth planes:

- `src/production_debt.py` + `src/resources/production_debt.json`;
- `src/production_debt_pr149.py` + `src/resources/production_debt_pr149.json`;
- duplicate PR-number implementations for policy admission, market economics, transaction proof and release path;
- isolated side-effect-free gate modules that are not yet active CLI/runtime owners.

## What this PR adds

- `src/canonical_readiness.py` defines one canonical machine-readable readiness state.
- Stable semantic `domain_id` values are required; PR numbers are changelog references only.
- Every requirement records one production owner module.
- Every implemented/integrated requirement needs active architecture proof:

```text
canonical CLI
→ composition root
→ exact owner module
```

- Every implemented/integrated requirement also needs package binding proof:

```text
source digest
wheel digest
distribution version
active import owner
source/wheel parity
```

- Duplicate active owners and duplicate legacy truth planes fail closed.
- Descriptor-only evidence and isolated gate modules cannot close integration requirements.
- Superseded requirements must include a removal criterion.

## Current canonical owner mapping

```text
policy.admission   -> src.pr153_policy_admission
market.economics   -> src.market_economic_kernel_pr154
transaction.proof  -> src.transaction_proof_pr155
runtime.paper      -> src.durable_paper_runtime_pr156
release.path       -> src.release_path_pr157
production.debt    -> src.canonical_readiness
```

The initial helper intentionally marks this owner map as blocked until active CLI/runtime/wheel binding is proven.

## Non-goals

This PR does not yet delete or rewrite the older engines. It provides the canonical authority and fail-closed migration contract so follow-up integration can safely demote/remove duplicate production-debt systems and PR-number truth planes.

This PR does not:

- enable live;
- claim paper readiness;
- claim production readiness;
- mutate production inventories;
- call providers/RPC;
- import signers/senders;
- fabricate source/wheel parity;
- let isolated gate modules close integration requirements.

## Suggested verification

```bash
python -m pytest tests/test_pr174_canonical_readiness.py -q
python -m compileall -q src tests
```

## Acceptance coverage started

| PR-174 acceptance item | Status in this PR |
|---|---|
| One authoritative readiness/debt system | New canonical schema + evaluator |
| Parallel truth planes detected | `LegacyTruthReport` divergence/multiplicity blockers |
| One owner per production domain | duplicate active requirement/owner blockers |
| Active CLI/runtime import path proof | `ArchitectureBindingProof` required |
| Isolated gate cannot close integration | explicit blocker + test |
| Source/wheel identical result | `PackageBindingProof` required |
| Superseded modules absent from production wheel | modeled as package/owner/removal blocker |
| Durable/auditable transitions | stable implementation/evidence states |
| PR renumbering does not alter schema | stable semantic domain IDs |
| 34 blockers map to canonical registry | owner-map helper starts migration path |
