# MPR-27 — Provider routing quota integrity gate

This PR starts the V11 **MPR-27 — Authenticated rooted provider, routing and
Jupiter/Helius quota integrity plane** boundary.

The uploaded V11 roadmap says the current repository is still **not paper-ready,
not shadow-qualified, not live-ready and not production-ready**. It also says
the fastest path is not more disconnected proof islands: MPR-25 must first make
the installed artifact and release qualification authoritative, then MPR-26,
MPR-27 and MPR-28 can converge the durable authority, providers and exact
economics before MPR-29 can claim sender-free readiness.

## Scope of this slice

This is a dependency-gated, offline, side-effect-free acceptance contract for
MPR-27. It does **not** claim the full MPR-27 deletion/cutover is done.

It makes the following obligations executable and fail-closed:

- recorded JSON cannot remain production provider input;
- RPC/Helius/Jupiter observations must be materialized as provider-owned,
  content-addressed evidence;
- one bounded transport owner must enforce total deadline, response size,
  decompression size, JSON depth, duplicate-key rejection, finite-number policy,
  schema quarantine, bounded cancellation, retry-storm policy and redaction;
- DNS preflight must bind to the actual peer IP and TLS origin;
- private/link-local/loopback destinations and redirect escapes must be denied;
- provider registry must be signed, unique and independent by provider,
  operator and network path;
- Jupiter/RPC quota and circuit authority must be cross-process, request-bound,
  generation-bound and restart-safe;
- quote identity must be collision-proof and include provider, cluster, mint
  pair, amount, mode, slippage, route params, policy generation and request
  hash;
- executable quote freshness must come from trusted slot/time;
- missing expiry, future timestamp, NaN/Infinity age, stale slot and route
  mutation must block execution;
- Helius ingress must ACK only after durable audit/event commit and must remain
  a hint queue, not a source of truth;
- old provider digest strings, injected client escape hatches, recorded JSON
  production adapters and RPC-storm slot-gap logic must be deleted or
  hard-disabled.

## Added files

- `src/mpr27_provider_routing_quota_integrity_gate.py`
- `tests/test_mpr27_provider_routing_quota_integrity_gate.py`
- `docs/mpr27_provider_routing_quota_integrity_gate.md`

## Safety boundary

This PR does **not** enable:

- provider network calls;
- executable candidate admission;
- live trading;
- signer/private-key access;
- sender/RPC/Jito submission;
- production-paper promotion;
- Docker/deployment changes.

A passing report only allows review of the MPR-27 provider-plane evidence
contract:

```text
provider_plane_review_allowed=true
executable_candidate_allowed=false
provider_network_allowed=false
paper_ready_allowed=false
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
private_key_material_allowed=false
```

## Verification

Focused local verification before opening:

```bash
PYTHONPATH=/mnt/data/mpr27_gate python -m py_compile \
  /mnt/data/mpr27_gate/src/mpr27_provider_routing_quota_integrity_gate.py \
  /mnt/data/mpr27_gate/tests/test_mpr27_provider_routing_quota_integrity_gate.py

PYTHONPATH=/mnt/data/mpr27_gate python -m pytest -q \
  /mnt/data/mpr27_gate/tests/test_mpr27_provider_routing_quota_integrity_gate.py
# 19 passed
```

The local sandbox emitted the unrelated artifact_tool spreadsheet warmup warning
on Python startup; both commands returned exit code 0.

## Remaining physical MPR-27 work

This PR does not replace the active provider/routing implementation. Follow-up
cutover must wire this contract into the installed product graph from MPR-25 and
the durable authority from MPR-26, then delete or hard-disable every bypass it
replaces.

Full MPR-27 completion still requires:

1. provider-owned rooted intake replacing recorded JSON as production input;
2. one installed transport owner used by every provider route;
3. target peer/TLS binding in actual provider clients;
4. signed provider registry and independent quorum enforcement;
5. cross-process Jupiter/RPC quota/circuit persistence;
6. collision-proof quote cache/admission identity in active routing;
7. Helius durable queue/backfill hooked into the central authority;
8. negative provider vectors and resource-budget probes run from the installed
   artifact;
9. production debt closure only after materialized evidence proves the real
   path, not this standalone evaluator.
