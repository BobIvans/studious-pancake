# MPR-18 — Canonical installed product, artifact truth and release qualification

This PR starts the V9 MPR-18 boundary as a deterministic, side-effect-free
acceptance gate. It targets the first blocking vertical from the V9 roadmap:
one installed product surface, one canonical runtime composition and one release
artifact truth before MPR-19 through MPR-24 can trust downstream evidence.

## Scope implemented in this checkpoint

- Adds `src/mpr18_canonical_installed_product_gate.py`.
- Adds `tests/test_mpr18_canonical_installed_product_gate.py`.
- Encodes the exact V9 MPR-18 coverage set:
  - new findings: `F-366`, `F-367`, `F-368`, `F-371`, `F-372`,
    `F-373`, `F-435`, `F-436`, `F-437`;
  - carry-forward closure: `F-270` through `F-280` and `F-361` through
    `F-364`.
- Requires installed command coverage for:
  - `flashloan-bot container`;
  - `flashloan-bot paper`;
  - `flashloan-bot shadow`;
  - `flashloan-bot status`;
  - `flashloan-bot capabilities`.
- Requires one installed composition root and one durable schema for container,
  paper and shadow.
- Requires safe-idle to remain diagnostic-only and unable to satisfy readiness
  or promotion.
- Requires source, wheel and image inventories to match policy and clean-wheel
  imports/resources to be proven from package resources.
- Requires checked-in build trees, egg-info, source launchers and PM2/setup
  bypasses to be removed or blocked.
- Requires a single dependency graph, offline wheelhouse, SBOM, provenance,
  digest-pinned base image and full-SHA action inventory.
- Requires authority map, capability contract, contracts mirror and quality
  inventory to converge on one versioned source of truth.

## Safety boundary

This checkpoint does not build a release artifact, mutate deployment files,
load keys, open signer IPC, call RPC/Jito/providers, sign transactions or submit
transactions.

A passing report still hard-codes:

```text
live_execution_allowed=false
sender_allowed=false
signer_allowed=false
```

The only positive state is:

```text
ready_for_mpr19_mpr20
```

That means the artifact/composition evidence contract is coherent enough for
MPR-19 and MPR-20 review. It is not paper-ready, shadow-qualified, live-ready or
production-ready.

## Focused verification

```bash
PYTHONPATH=. python -m py_compile \
  src/mpr18_canonical_installed_product_gate.py \
  tests/test_mpr18_canonical_installed_product_gate.py

PYTHONPATH=. python -m pytest -q \
  tests/test_mpr18_canonical_installed_product_gate.py
```

The focused suite covers:

1. a passing sender-free evidence envelope;
2. exact finding coverage with no missing, duplicate or unknown findings;
3. one installed container/paper/shadow composition root;
4. required installed CLI surfaces;
5. clean artifact truth from source/wheel/image inventory and E2E trace;
6. deletion/blocking of generated trees and source-launcher bypasses;
7. one versioned authority/quality source and authoritative CI truth;
8. forbidden live/signer/sender/source-launcher reachability;
9. deterministic JSON reports.

## Remaining full MPR-18 materialization

This PR is the first V9 MPR-18 reviewable gate, not the physical completion of
all release work. Follow-up commits must wire this contract into the real
installed-artifact qualification flow, materialize signed source/wheel/image
manifests, generate the runtime call graph, produce SBOM/provenance/wheelhouse
artifacts, delete or quarantine bypass paths and make the authoritative CI check
consume the exact clean installed wheel/image.
