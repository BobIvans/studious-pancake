# MPR-25 — Canonical product graph, artifact truth and mandatory qualification gate

This checkpoint starts MPR-25 from the V11 production-readiness roadmap.

MPR-25 is the first required cutover boundary: later durability, provider,
execution, paper workload, signer and promotion work cannot be trusted until the
installed product graph and release qualification truth are authoritative.

## What this slice adds

- `src/mpr25_canonical_product_graph_artifact_truth_gate.py`
- `tests/test_mpr25_canonical_product_graph_artifact_truth_gate.py`
- this document

The module is side-effect free. It validates a materialized MPR-25 evidence
bundle and refuses to claim paper/shadow readiness unless all of the following
are true:

- one product authority, one release-set manifest and one composition root;
- the production graph is generated from the installed wheel and console scripts;
- the five public commands are part of one clean-install surface policy;
- every `src` module is reachable, explicitly experimental, or quarantined with
  owner and expiry;
- required authorities have exactly one production caller;
- source launchers, PM2-style bypasses, legacy gates and declaration-only release
  checks are retired or demoted;
- build truth is hash-locked, signed, offline-installable and reproducible;
- workflows are collapsed to a small required set and all external action refs
  are immutable full commit SHAs;
- formatter/type/test inventories cover tracked Python instead of historical
  hand-picked lists;
- pytest collection/import errors and reachable production asserts are zero;
- artifact evidence is materialized from bytes, signed, fresh and non-placeholder.

## Safety boundary

This slice does not build wheels/images, inspect Docker/GitHub Actions, read
files/env/config, import providers or Solana SDKs, open signer IPC, call RPC/Jito
/Jupiter/MarginFi/Helius, submit transactions, or enable live execution.

A passing report still hard-codes:

```text
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
```

The only positive state is readiness for MPR-25 cutover review. The full MPR-25
PR must still replace active release gates and product graph generation, not keep
this gate as another proof island.

## Remaining full MPR-25 work

1. Replace the historical PR-01/PR-10 authority map with a production completion
   ledger that understands MPR-25+.
2. Generate product surface and reachability manifests from the installed wheel
   and console-script graph.
3. Make `flashloan-bot`, `flashloan-bot-healthcheck`, `flashloan-contracts`,
   `flashloan-checks` and `flashloan-release-evidence` one clean-install policy.
4. Delete or hard-disable source launchers, PM2-style paths and safe-idle
   readiness bypasses.
5. Unify requirements, pyproject, wheelhouse, SBOM and image provenance into one
   hash-locked build truth.
6. Collapse workflows and pin every external action to a full commit SHA.
7. Replace partial formatter/type/test manifests with generated tracked-Python
   inventories.
8. Make `verify_repo` an artifact-based DAG and require zero pytest collection
   errors from a disposable environment.

## Verification

```bash
PYTHONPATH=. python -m py_compile \
  src/mpr25_canonical_product_graph_artifact_truth_gate.py \
  tests/test_mpr25_canonical_product_graph_artifact_truth_gate.py

PYTHONPATH=. python -m pytest -q \
  tests/test_mpr25_canonical_product_graph_artifact_truth_gate.py
# 15 passed
```
