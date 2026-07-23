# PR-221 Rooted Protocol, Provider, Discovery and ML Integrity Gate

This document records the first safe PR-221 acceptance-contract slice for the
409-finding mega-roadmap.

## Scope

PR-221 owns the rooted data plane between official protocol contracts, provider
responses, Solana state, conservative opportunity admission and reproducible
decision datasets. It is downstream of PR-219 and PR-220 and must not create an
executable opportunity unless canonical product/release truth and durable control
plane truth are already accepted.

This slice adds a side-effect-free gate only. It does not contact any provider,
Solana RPC endpoint, Helius webhook, Jupiter endpoint, MarginFi service, signer,
sender or live runtime.

## Covered roadmap areas

The gate requires evidence for:

- accepted and materialized PR-219 and PR-220 dependencies;
- all PR-221 finding IDs from the mega-roadmap ownership table;
- materialized protocol/IDL/program/endpoint registry evidence;
- a single strict transport owner with HTTPS allowlist, DNS/IP revalidation,
  redirect policy, strict JSON semantics, byte/depth/key budgets and redaction;
- endpoint, credential, quota, plan and environment generation binding;
- rooted observation lineage around provider calls: slot before/after,
  minContextSlot, blockhash window, genesis, fork/skew and backfill;
- a single Jupiter Swap V2 adapter with legacy V1 retired and no fabricated
  contextSlot;
- Helius as authenticated hint-only ingress with rooted RPC backfill;
- conservative discovery based on guaranteed minimum output, route continuity,
  artifact digest, freshness, amount/slot coupling and deterministic value/risk;
- opportunity-domain integrity: finite values, u64/base-unit money, deep freeze,
  evidence-aware identity and bounded queues;
- ML dataset integrity: no temporal leakage, exact label provenance, canonical
  UTC timestamps, atomic manifests, group-aware splits, OOD gates and minimum
  sample policy;
- adversarial drills against the installed sender-free runtime.

## Safety boundary

A passing report may only allow sender-free data-plane review:

```text
executable_opportunity_allowed=true
decision_dataset_allowed=true
provider_network_allowed=false
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
```

The `provider_network_allowed=false` value is intentional in this slice. Real
provider/RPC calls must remain outside this module and can only be exercised by
later installed-artifact qualification harnesses.

## Verification

Focused local verification used for this slice:

```bash
PYTHONPATH=/mnt/data/pr221_gate python -m py_compile \
  /mnt/data/pr221_gate/src/pr221_rooted_protocol_provider_ml_gate.py \
  /mnt/data/pr221_gate/tests/test_pr221_rooted_protocol_provider_ml_gate.py

PYTHONPATH=/mnt/data/pr221_gate python -m pytest -q \
  /mnt/data/pr221_gate/tests/test_pr221_rooted_protocol_provider_ml_gate.py
# 14 passed
```

## Remaining full PR-221 work

This gate is not the full physical implementation. Later PR-221 commits must wire
the contract into the real provider registry, transport manager, Helius ingress,
Jupiter V2 adapter, Solana rooted observation collector, discovery runtime,
opportunity domain and ML dataset builder. The real implementation must replace
legacy V1/generic parsers rather than adding another proof island beside them.
