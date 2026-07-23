# PR-214 — Architecture Retirement and Domain/Schema Consolidation Gate

This is the first Pass 7 PR-214 acceptance-contract slice.

The Pass 7 audit assigns PR-214 to architecture retirement and domain/schema
consolidation.  The central failure mode is that the repository keeps adding
new PR-numbered modules, schema IDs and lifecycle/store generations without a
single installed composition root deciding what is promoted, library-only,
tooling, archived or deleted.

## Scope

This slice adds an offline fail-closed evidence gate:

- every installed/source module must have a disposition: `promoted`, `library`,
  `tooling`, `archive` or `delete`;
- reachable installed-runtime modules may only be `promoted` or `library`;
- new PR-numbered runtime filenames are forbidden;
- reachable historical compatibility shims need explicit expiration;
- every schema ID must be owned, unique and lifecycle-classified;
- canonical domain vocabulary must own commitment and lifecycle state types;
- public durability API must expose one `LifecycleStore` protocol and one
  production implementation;
- historical lifecycle stores must not be public exports or reachable from the
  composition root;
- import cycles and import-time global monkeypatching are release blockers;
- `legacy_arb_bot` must be archived/deleted/quarantined and unreachable;
- mega-class/module size debt needs owners or decomposition plans;
- reachability evidence must be generated from the installed artifact;
- live, signer and sender capabilities remain forbidden.

## Covered Pass 7 findings

- F-269 — unreachable source modules outside installed composition roots.
- F-270 — historical PR names in active import graph.
- F-271 — version-by-filename architecture.
- F-272 — schema IDs without a single registry/compatibility graph.
- F-273 — parallel enum/state taxonomies.
- F-274 — duplicated commitment-level definitions.
- F-275 — multiple coequal lifecycle authorities.
- F-276 — Helius import-time class identity mutation.
- F-277 — import graph cycles.
- F-278 — legacy runtime monolith.
- F-279 — source-only megaclasses.

## Safety boundary

This PR does **not** enable:

- live trading;
- signer/private-key access;
- sender/RPC/Jito submission;
- provider network calls;
- transaction construction or simulation;
- runtime entrypoint cutover;
- deletion of legacy modules.

A passing report only means the evidence bundle proves the architecture
retirement contract.  It does not mean the full PR-214 cleanup has been
physically completed.

## Verification

```bash
python -m py_compile \
  src/mpr214_architecture_retirement_gate.py \
  tests/test_mpr214_architecture_retirement_gate.py
python -m pytest -q tests/test_mpr214_architecture_retirement_gate.py
```

## Remaining full PR-214 work

Later slices must wire this contract to an installed-artifact reachability
generator, build a real schema registry from source/wheel resources, migrate
promoted APIs into stable domain names, quarantine historical lifecycle stores,
remove import-time monkeypatching/cycles, and physically retire or archive
legacy megaclasses under a signed migration plan.
