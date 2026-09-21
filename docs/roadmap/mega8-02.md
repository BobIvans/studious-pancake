# MEGA8-02 — Rights-aware graph, robust execution solver and Solana structural assets

Implementation base: `04480fa25d1117e9d20e7fe8caad23b16cd5ef4a`.

## Boundary

This PR implements PR-163–PR-185 / NF-401–NF-492 as a deterministic offline contract layer.
It does not create a signer, sender, RPC client, transaction submission path, secret surface,
or live/capital permission. Code merge, offline qualification, shadow qualification and live
authorization remain distinct states.

MEGA8-01 is still a prerequisite for integrated eight-pack promotion. This PR does not claim
that MEGA8-01 is closed; it only keeps MEGA8-02 independently testable and research-only.

## Canonical reuse

MEGA8-02 extends rather than replaces existing owners:

- `src/routing/route_graph.py` for canonical provider-normalized route identity.
- `src/strategy/multihop_solver.py` for bounded cycle search.
- `src/strategy/conflict_scheduler.py` for shared-resource scheduling.
- `src/economics/split_flow.py` for joint split-flow economics.
- `src/execution/exact_simulation.py` for canonical exact simulation authority.
- `src/execution/financing_evidence.py` for financing evidence.
- `src/direct_venue/super03.py` for fail-closed direct-venue conformance.

No external source was copied or vendored. Candidate upstream projects in the roadmap remain
references until their exact deployment/version/license and differential vectors are admitted
by the existing provenance authorities.

## Child ownership

| Child | Stage | NF | Owner | Status |
|---|---|---|---|---|
| PR-163 | GRAPH-02 | NF-401–404 | `src/mega8_02/pr163.py` | IMPLEMENTED_OFFLINE |
| PR-164 | GRAPH-03 | NF-405–408 | `src/mega8_02/pr164.py` | IMPLEMENTED_OFFLINE |
| PR-165 | ROUTE-01 | NF-409–412 | `src/mega8_02/pr165.py` | IMPLEMENTED_OFFLINE |
| PR-166 | GRAPH-04 | NF-413–416 | `src/mega8_02/pr166.py` | IMPLEMENTED_OFFLINE |
| PR-167 | SIM-03 | NF-417–420 | `src/mega8_02/pr167.py` | IMPLEMENTED_OFFLINE |
| PR-168 | PREDICT-01 | NF-421–424 | `src/mega8_02/pr168.py` | IMPLEMENTED_OFFLINE |
| PR-169 | PREDICT-02 | NF-425–428 | `src/mega8_02/pr169.py` | IMPLEMENTED_OFFLINE |
| PR-170 | FEE-01 | NF-429–432 | `src/mega8_02/pr170.py` | IMPLEMENTED_OFFLINE |
| PR-171 | SOLVER-03 | NF-433–436 | `src/mega8_02/pr171.py` | IMPLEMENTED_OFFLINE |
| PR-172 | SOLVER-04 | NF-437–440 | `src/mega8_02/pr172.py` | IMPLEMENTED_OFFLINE |
| PR-173 | SOLVER-05 | NF-441–444 | `src/mega8_02/pr173.py` | IMPLEMENTED_OFFLINE |
| PR-174 | CAPITAL-03 | NF-445–448 | `src/mega8_02/pr174.py` | IMPLEMENTED_OFFLINE |
| PR-175 | TXVAR-01 | NF-449–452 | `src/mega8_02/pr175.py` | IMPLEMENTED_OFFLINE |
| PR-176 | PROOF-01 | NF-453–456 | `src/mega8_02/pr176.py` | IMPLEMENTED_OFFLINE |
| PR-177 | SOLANA-CONFIG-01 | NF-457–460 | `src/mega8_02/pr177.py` | IMPLEMENTED_OFFLINE |
| PR-178 | ORACLE-02 | NF-461–464 | `src/mega8_02/pr178.py` | IMPLEMENTED_OFFLINE |
| PR-179 | STABLE-01 | NF-465–468 | `src/mega8_02/pr179.py` | IMPLEMENTED_OFFLINE |
| PR-180 | VAULT-01 | NF-469–472 | `src/mega8_02/pr180.py` | IMPLEMENTED_OFFLINE |
| PR-181 | YIELD-01 | NF-473–476 | `src/mega8_02/pr181.py` | IMPLEMENTED_OFFLINE |
| PR-182 | LST-02 | NF-477–480 | `src/mega8_02/pr182.py` | IMPLEMENTED_OFFLINE |
| PR-183 | LST-03 | NF-481–484 | `src/mega8_02/pr183.py` | IMPLEMENTED_OFFLINE |
| PR-184 | LP-01 | NF-485–488 | `src/mega8_02/pr184.py` | IMPLEMENTED_OFFLINE |
| PR-185 | POL-01 | NF-489–492 | `src/mega8_02/pr185.py` | IMPLEMENTED_OFFLINE |

## Verification

Focused tests:

- `tests/test_mega8_02_manifest.py`: exact 23-child/92-function ownership and sender-free imports.
- `tests/test_mega8_02_graph_solver.py`: rights, hyperedges, route identity, state transitions,
  resource/fee/contention prediction, Pareto/mixed/robust solver, financing variants,
  transaction variants and certificate replay.
- `tests/test_mega8_02_solana_assets.py`: program/config changes, oracle timing, stablecoin,
  vault, yield, LST/stake-account, LP and protocol-owned-inventory contracts.

The dedicated workflow also imports the installed package outside the checkout, compiles all
MEGA8-02 modules, runs Black, executes the focused suites plus selected existing-owner
regressions, and verifies the coverage manifest remains default-off.

## Rollback and residual blockers

Rollback is code/config rollback only; the package has no external effects to undo. Evidence
identities remain content-addressed. Residual blockers for any production or capital claim:

1. Full MEGA8-01 eight-pack prerequisite closure is not claimed here.
2. Deployment-specific Solana program/SDK/license/differential conformance is not claimed.
3. No shadow/live promotion or capital increase is granted by these modules.
