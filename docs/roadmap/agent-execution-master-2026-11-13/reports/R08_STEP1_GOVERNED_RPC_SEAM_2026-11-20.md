# R08-step1 — governed-RPC composition seam (lane report)

**Lane:** R08-step1 (wave-3). **Implemented:** 2026-11-20. **Base:** main
`0c134f89` (worktree branch `agent/r08-governed-rpc-seam`).

## What it implements (audit §6 step 1, verbatim contract)

Injects a **deployment-supplied governed RPC** into `CoreV1Dependencies.rpc`,
replacing `_ResolverBlockedRpc` — composition-only, smallest-first, live stays
hard-denied. Contract tests required by the audit are all present:

1. **resolver accepts governed transport only** — the transport must be a
   deployment-owned object with the async `call(method, params)` shape
   (`RpcClient` structural protocol); anything else is a typed
   `CORE_V1_GOVERNED_RPC_TRANSPORT_INVALID` refusal. The resolver constructs
   NO network transport of its own (structurally tested: no
   requests/httpx/aiohttp/urllib/socket imports).
2. **blocked-RPC default preserved when absent** — no manifest descriptor, or
   descriptor without a supplied transport ⇒ `_ResolverBlockedRpc` remains the
   default (`dependencies=None` + typed blocker
   `CORE_V1_GOVERNED_RPC_TRANSPORT_REQUIRED`); every existing resolution
   result is byte-identical to before.
3. **simulation evidence hash binding** — the manifest pins a
   `governed_rpc` descriptor (`GovernedRpcDescriptor`: https, credential-free,
   no query/fragment, rooted path, `deployment_generation ≥ 1`); its stable
   identity fingerprint (sha256 over endpoint+generation) is returned on
   `InstalledDependencyResolution.governed_rpc_fingerprint` so downstream
   simulation evidence can be bound to the transport identity — stable across
   equivalent deployment transports.

## Pairing discipline (fail-closed)

| Manifest | Transport | Result |
|---|---|---|
| no descriptor | none | historical blocked default (unchanged) |
| descriptor present | none | `dependencies=None`, blocker `CORE_V1_GOVERNED_RPC_TRANSPORT_REQUIRED` |
| descriptor present | transport supplied | `rpc=<transport>` (identity preserved) + fingerprint bound |
| no descriptor | transport supplied | loud typed `CORE_V1_GOVERNED_RPC_DESCRIPTOR_REQUIRED` error |
| malformed descriptor / non-callable transport | — | typed `CORE_V1_GOVERNED_RPC_*_INVALID` errors |

A manifest flag ALONE can never produce a network-capable transport (tested:
`{"enabled": true}` descriptor still blocks without the deployment object).
The draft source stays blocked in every resolution — only the RPC seam is
open; R04/R05/R06 dependency gates are untouched. The marginfi legacy profile
path is unchanged. `src/runtime/core_v1_composition.py` required NO
modification (it already consumes `dependencies.rpc` into
`ExactSimulationFinalizer`).

## Exact changed paths

- `src/runtime/core_v1_dependency_resolver.py` — resolver seam (owner
  preserved; additive keyword-only `governed_rpc_transport`, new
  `GovernedRpcDescriptor` + typed codes, `governed_rpc_fingerprint` field).
- `tests/test_r08_step1_governed_rpc_seam.py` — NEW contract tests (18).
- `docs/roadmap/agent-execution-master-2026-11-13/reports/R08_STEP1_GOVERNED_RPC_SEAM_2026-11-20.md` — this report.

## Test evidence (offline, pytest-socket)

- New: 18 tests — blocked defaults (absent manifest / resolved manifest
  without descriptor, blocked RPC call refuses), governed wiring (identity
  preserved, fingerprint stability, RpcClient shape), pairing mismatches,
  descriptor validation negatives (http, credentials, query, fragment, bad
  generation), live-still-denied (draft source blocked, no network imports,
  flag-alone blocks).
- Regression: `tests/test_agg03_dependency_resolver.py` unchanged and green
  (13 passed).
- Exact counts recorded in the PR body at open time.

## Blockers / deferred

- Steps 2-8 of the audit plan (builders, capacity, quotes, rent, drafts,
  R05/R06 qualification) remain separate lanes; none may be closed by env,
  `config/capabilities.json` or strategy-registry edits.
- Live remains hard-denied: the seam moves ONE dependency (simulation RPC)
  from "always blocked" to "deployment-supplied only".
