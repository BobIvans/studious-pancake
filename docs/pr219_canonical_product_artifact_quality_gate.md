# PR-219 canonical product artifact quality gate

This slice starts **PR-219 — Canonical Product, Artifact and Quality Truth** from
 the mega-roadmap.

It is a narrow reviewable acceptance gate for the PR-219 boundary. It does not
rewrite the runtime or complete the whole cutover. Instead, it defines one
deterministic evidence contract that later PR-219 implementation work must
satisfy before the repository can claim one canonical installed sender-free
product.

## Scope

- require one canonical sender-free product identity and composition root;
- require the five public installed CLI contracts;
- require installed-wheel reachability for required controls;
- fail closed if sender, signer or live namespaces remain packaged;
- fail closed if checked-in build artifacts or source launchers bypass the
  installed release;
- fail closed if workflow actions or base images remain mutable;
- fail closed if reachable production asserts, import cycles, broad quarantine
  or ambient qualification dependencies remain;
- require offline verified build inputs, signed wheelhouse and source/wheel/image
  surface parity.

## Non-goals

This PR does not:

- enable live trading;
- enable signer or sender execution;
- mutate deployment manifests;
- build or publish wheels/images;
- delete legacy paths automatically;
- perform the full PR-219 architectural cutover.

A passing report still returns:

```text
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
```

## Verification

```bash
python -m py_compile \
  src/pr219_canonical_product_artifact_quality_gate.py \
  tests/test_pr219_canonical_product_artifact_quality_gate.py

python -m pytest -q \
  tests/test_pr219_canonical_product_artifact_quality_gate.py
```
