# AGG-14 — Research system and verifiable product experiments

Base reviewed for this implementation: \`main@0c4f216a62d62b20f6fb4ec4bbd0548cea58df65\`.

## Scope

This change implements the offline/default-off code boundary for AGG-14 work packages
\`RND-01\`, \`RND-02\`, \`RND-03\`, \`PRODUCT-01\`, and \`RND-04\` covering NF-308…NF-323.
It does **not** claim external Kora, quantum hardware, federated participant, ZK,
customer, grant, or production qualification evidence that has not been observed.

The package is deliberately sender-free:

- no private-key loading;
- no signer initialization;
- no transaction submission;
- no RPC/Jito execution transport;
- no remote account/service mutation;
- no live trading enablement;
- no automatic risk/capital increase.

## Existing owners preserved

AGG-14 does not replace existing runtime/economic authorities. The existing
\`src.ai_advisory\` gate remains the authority for AI model advisory evidence;
MPR-15 treasury remains the financial movement/accounting authority; MPR-2618
remains the credential/trust rotation authority; \`src.external_resources\` remains
the explicit remote-resource plan/apply boundary.

\`src.research\` owns only research evidence, reproducible benchmark records,
product experiment plans, product/research attribution, and promotion-to-review
decisions. \`RevenueAttributionLedger\` is explicitly **not** a trading capital or
settlement authority; it exists to prevent service/grant/rebate/rent/client money
from inflating arbitrage PnL.

## Work package behavior

### RND-01 — NF-308…NF-312

- content-addressed research source/claim/hypothesis registry;
- source status and independent-proof groups;
- cited AI research output with missing-symbol detection;
- developer workflow receipt that forbids password/private-key collection;
- planner/critic/runner records where agent agreement is not market proof;
- defensive-tool benchmark records that never grant execution authority.

### RND-02 — NF-313…NF-315

- end-to-end benchmark measurement includes preparation, transfer, queue,
  compute, verification, cost and memory;
- QUBO comparison requires an equal-budget classical baseline and exact economic
  recheck;
- quantum/time-series experiments require the same holdout data and cannot import
  paper accuracy as our measured result;
- accelerator comparison requires exact output vectors and measures whole-pipeline
  latency rather than kernel-only latency.

### RND-03 — NF-316…NF-317

- federated experiment contract requires consent, a threat model, communication
  cost and bounded malicious updates; raw private-data exfiltration fails closed;
- verifiable-computation records pin statement/circuit/public inputs/verifier and
  full prover/verify overhead; a valid proof is forbidden from being labelled as
  proof that source market data is true.

### PRODUCT-01 — NF-318…NF-322

- Kora/paymaster planning checks external capability, funded fee payer, payment
  asset, transaction roles and sponsor/request/loss caps; the result still cannot
  sign or submit;
- keeper plans bind customer account/action scope and worst debit, and explicitly
  exclude client funds from trading capital;
- data/evidence API policy distinguishes observed/simulated/demo artifacts,
  distribution rights, staleness, access scopes and query budgets;
- grant/bounty/disclosure receipt requires identity/private-detail approval and
  cannot claim submission/revenue or unsolicited exploitation;
- product attribution separates arbitrage PnL, service fees, rebates, grants,
  rent recovery, investments and client funds, and rejects one external event
  being double-attributed to trading and product revenue.

### RND-04 — NF-323

Research promotion is fail-closed. A positive benchmark can reach only
\`scoped-integration-review\` after reproducibility, end-to-end cost, safety,
integration tests and resource-policy checks. It never grants execution authority
or production readiness. A reproducible negative result becomes
\`rejected-with-evidence\` rather than being erased from the research registry.

## Evidence and blockers

\`config/agg14_research_coverage.json\` lists all 16 primary NF and preserves
external/operational blockers. \`IMPLEMENTED_OFFLINE\` means the domain contract,
validation and focused tests exist; it does not mean the corresponding external
service/hardware/customer experiment ran.

Important remaining evidence includes actual defensive-tool qualification,
QUBO/accelerator measurements, a concrete FL/ZK use case, an externally attested
Kora capability with funded sponsor inventory, customer keeper authorization,
data-product customer/payment evidence, and any real grant/bounty submission.

## Focused verification

\`\`\`bash
python -m compileall -q src/research tests/test_agg14_research_system.py scripts/verify_agg14_research.py
python -m pytest tests/test_agg14_research_system.py -q
python scripts/verify_agg14_research.py --json
\`\`\`

Repository-wide CI remains authoritative for compatibility, packaging, secret
scanning and all existing safety gates.

## Rollback

Revert the AGG-14 commits or remove the default-off \`src.research\` package and
coverage artifact. No ledger migration, signer state, remote resource, account,
transaction or live-mode rollback is required because this change performs none
of those effects.
