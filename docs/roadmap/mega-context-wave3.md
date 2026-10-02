# MEGA Context / Evidence / Wave 3 unification

This PR executes the supplied one-shot MEGA pack as a bounded, offline/read-only
context workbench. It does **not** create a second trading runtime or a second
signer/sender/release authority.

## Implemented merge-blocking scope

- BASE context builder foundation: inventory, hashes, sensitive/generated policy,
  exact-byte roundtrip evidence, history/snapshot boundaries, Python symbols and
  imports, context budgets, archive/task views, chunk maps and staleness detection.
- SPX P0 evidence/hardening: source discrepancy preservation, requirement/evidence
  cards, claim classes, reuse review, counterevidence packs, safe follow-up paths,
  audit progress, patch envelopes, structured handoff, code/config/lock-bound test
  receipts, CI evidence semantics, campaign sealing, sender-free boundary,
  pipeline outcome classes, evidence provenance, operator gates, credential
  isolation, context delivery receipts and blocker-vs-idea separation.
- Wave 3 P0 workbench: typed entities, observed/declared/derived truth classes,
  source restriction inheritance, inert schema-driven rendering, goal/evidence
  cards, context basket, large-document viewports, reviewed action registry,
  plan -> exact grant -> execution re-authorization, shared policy across
  UI/CLI/MCP, permission-aware retrieval, sub-chunk indexing, bounded graph
  expansion, citation validation, implementation briefs, market evidence lanes,
  connector health, destination previews, golden questions, evidence-completeness
  metrics, adversarial UI policy checks, drift propagation and reuse/benefit gates.

## Catalog disposition

The checked-in status matrix preserves all **263 source rows** and has no
\`TODO_RECONCILE\`:

- BASE: 95 IMPLEMENTED
- SPX: 50 IMPLEMENTED, 46 BLOCKED
- W3: 60 IMPLEMENTED, 12 BLOCKED

All SPX/W3 P0 IDs from the supplied manifest are IMPLEMENTED. Remaining BLOCKED
rows are non-P0 work that requires external providers/models/connectors,
domain-specific owners, or post-release observation. BLOCKED is explicit missing
work and is not reported as completed.

The original catalog discrepancy is preserved: Markdown has 95 BASE entries,
JSON has 94, and BASE-54 is \`fetch_github_pr_metadata()\`.

## Safety boundary

This owner has no network client, subprocess execution, signer, transaction
submission, withdrawal, wallet mutation, live-trading switch or silent paid
provider fallback. Repository/web/AI text is data only. Approval is bound to the
exact plan and snapshot and is rechecked at execution.

## Verification

\`\`\`bash
python scripts/verify_mega_context_wave3.py
python -m pytest -q tests/test_mega_context_wave3.py
\`\`\`

Repository-wide CI remains authoritative. Merge does not imply production
qualification or live authorization.
