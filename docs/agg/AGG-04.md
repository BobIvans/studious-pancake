# AGG-04 — exact paper simulation and first full qualification

Branch scope: \`codex/agg-20260920-04\`.

This aggregate integrates the AGG-04 qualification semantics into the existing
canonical owners instead of creating another runtime, sender, ledger, or release
authority.

## What this change closes

The canonical MPR-2611 evidence owner (\`src/production_qualification.py\`) now
contains a sender-free AGG-04 campaign evidence boundary:

- frozen campaign/profile/source/scope policy before measurements;
- independent episode IDs separated from amount/route/message variants;
- immutable variant binding for amount, lender, route, state frame, cost and
  final message digests;
- horizon probes bound to the same variant/message generation;
- strict \`elapsed_ms > horizon\` semantics, with unknown probes preserved;
- right/interval-censored survival evidence rather than invented continuous
  profitability;
- nested A/E/C/S/H/N cohorts where retries and variants cannot inflate episode
  counts;
- disjoint temporal train/validation/holdout sets with embargo checks;
- selection-bias visibility and explicit unknown propensity;
- one-selected-variant-per-episode class statistics;
- paired baseline/challenger comparison with resource costs and unknown rows;
- counterfactual delay-stress labeling that cannot be presented as observed
  market outcome;
- scoped class verdicts: \`insufficient-evidence\`, \`negative\`, or
  \`qualified-scope\`;
- content-addressed evidence package and dashboard projection;
- demotion/requalification transition that cannot auto-rearm live execution.

Every resulting AGG-04 verdict hard-keeps:

- \`live_enabled=false\`;
- \`release_claim_allowed=false\`;
- \`production_ready=false\`.

## Existing owners reused

AGG-04 deliberately reuses the already merged canonical components:

- \`ExactSimulationFinalizer\` for final-message simulation and exact fee
  binding;
- PR118 non-monotonic sizing and typed multi-asset cost ledger;
- the amount-coupled \`CircularArbitrageDetector\`;
- MPR-2622 stable/correlated integer math and qualification;
- durable paper runner / atomic vertical;
- existing economic reconciliation.

The PR does not import legacy senders and does not add signing, submission,
funding, wallet mutation, remote resource mutation, or live activation.

## 41-NF coverage truth

\`config/agg04_qualification_coverage.json\` contains exactly all 41 primary NF
from AGG-04 and records each as implemented here, reused from current main,
partially available, or blocked. The manifest is intentionally not a completion
claim.

The remaining hard blockers on current main are explicit:

1. **NF-116 Raydium CPMM** — MPR-2617 reserves the family but current main does
   not contain deployed-vector executable conformance.
2. **NF-118 Meteora DLMM** — current deployed bin/dynamic-fee and
   \`consumedInAmount\` conformance is not established.
3. **NF-164 SVM transaction harness** — no pinned LiteSVM/Mollusk full-message
   harness is integrated into the canonical AGG-04 evidence path.
4. **NF-165 loaded mainnet-state integration** — no current Surfpool/fork
   evidence package is present.
5. **NF-174 full multi-family paper pass** — cannot be honestly promoted while
   the above venue/harness evidence remains missing.

Other partial rows in the manifest remain visible rather than being counted as
complete.

## Focused verification

The dedicated workflow compiles the changed qualification surface and runs the
new AGG-04 regressions plus existing MPR-2611 evidence validation tests.

The repository-wide CI remains authoritative and still runs the normal
repository verification, package smoke, image smoke and secret scan.

Suggested local focused command:

\`\`\`bash
python -m pytest -q \
  tests/test_agg04_qualification.py \
  tests/test_mpr2611_production_qualification.py
\`\`\`

This PR is safe to merge as default-off code only when current-head CI is green.
A code merge does not assert external qualification and does not authorize live
execution.
