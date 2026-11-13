# Flash-capital offline knowledge base — R-02 / R-03

**Updated:** 2026-11-13. This directory carries the broad protocol research base and implementation references for flash-capital readers. It is documentation and source-reference material; it does not create a live lender integration or execution authority.

## Start
1. \`CODEX_START_HERE.md\` — current R-02 task, with R-01 explicitly complete.
2. \`MASTER_CONTEXT.md\` — current mainline facts and status.
3. \`PROVIDER_SELECTION.md\` and \`PROVIDER_CATALOG.json\` — account/setup cost taxonomy and 27 candidate identifiers.
4. \`R02_ARCHITECTURE.md\`, \`R02_TESTS_AND_EXIT_GATES.md\` — existing owners, reader schema, proof requirements.
5. \`offline/README.md\`, \`SOURCE_LEDGER.json\`, \`CONTRACT_FACTS.json\`, three protocol dossiers, economics/selector and gaps.
6. The newer focused source pack in \`docs/roadmap/r02-capacity-recovery-2026-10-08/\` contains pinned SDK references and provider-specific R-02/R-03 contracts.

## Important distinctions
- The 27 catalog entries are research candidates, not 27 qualified or independent lenders.
- Router/aggregator, venue flash swap, ERC standard, rent sponsor and actual flash lender are different resource types.
- A protocol-reported asset list, documentation fee, TVL or vault token balance is not effective borrow capacity.
- Fees, account/ATA/receiver setup, native gas, rent, callback and exit costs must be separate; UNKNOWN is never zero.
- Keep the maximum research universe. Qualify capital providers independently and let later route selection connect a verified settlement hub to any verified target asset.
- R-02 means read-only current capital state. R-03 means unsigned, source-conformant builder contracts. Exact full transaction/PTB simulation and paper campaign are later gates.

## Offline verification
From repository root:
\`\`\`bash
python docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/verify_bundle.py
python docs/roadmap/r02-capacity-recovery-2026-10-08/offline/verify_offline.py
\`\`\`
These verifiers check local provenance/layout files without web requests; they do not prove live reserve state or deployed program compatibility. See license/provenance before reusing any mirrored source in shipped code.
