# CODEX START HERE — MASTER HANDOFF (RENEWED 2026-10-06)

This is the top-level handoff branch for PR #567.

## Do not restart the old sequence

Do **not** start again from QPR-01/QPR-02.

Stacked implementation PRs:
- QPR-01 — #568
- QPR-02 — #569
- QPR-03 campaign-start — #570

The next canonical continuation is:

**PR #571 — GPR V2.1: Asset/Representation Graph + Parallel Solana/Sui Qualification**

Branch:
`rnd/gpr-parallel-radar-2026-10-06`

Codex entrypoint there:
`docs/roadmap/gpr-parallel-radar-rnd-2026-10-06/CODEX_START_HERE.md`

## Important stack state

The public `main` branch does not yet represent the whole stacked qualification work. PR #567 remains the handoff/master PR.

PR #571 should be treated as the continuation/integration PR that brings the later QPR state plus the renewed GPR strategy back into this handoff branch.

## New objective

The next code PR is:

**GPR-01 — Asset/Representation Registry + Evidence-Classified Research Economic Graph + Verification Queue**

The renewed strategy includes:
- canonical research Solana mints;
- canonical Sui Move coin types;
- TON Jetton/master identities;
- representation-specific status gates;
- expanded Solana LST/LRT/stable/JLP graph;
- expanded Sui stable/BTC/LST graph;
- Solana<->Sui research-only economic topology.

Do not implement GPR-02+ until GPR-01 contracts/tests pass.

## Architecture rule

Think in:

```text
EconomicAsset
 -> Representation
 -> Chain
 -> Venue
 -> Transformation
```

not:

```text
ticker -> pair -> price
```

Discovery/router/reference data remains research evidence. Exact chain-local execution evidence still requires QPR-02/direct-state qualification and existing exact graph owners.

Cross-chain bridge/equivalence relations are non-atomic research/rebalance edges only.

## Safety

No signer.
No sender.
No submission.
No live capital.
No production promotion.

For implementation details, leave this master pack and continue from PR #571's `CODEX_START_HERE.md`.

## V2.1 first campaign

The renewed continuation now contains 91 research identities, 14 first-campaign families and 9 DeepBook read-only pool identifiers. Codex must implement independent `heat`, `execution_class` and `evidence_state` fields and the startup HARD_BOUND identity receipt before exact promotion.

See PR #571: `FIRST_CAMPAIGN_FAMILIES_V2_1.json` and `SUI_DEEPBOOK_POOLS_V2_1.json`.
