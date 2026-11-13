# Offline-first R-02 reference kit — 2026-10-08
**This is an original technical synthesis of inspected primary sources, not a redistributed full documentation mirror.** The docs links are provenance only. Codex can use this directory *without web access* to understand verified behavior, program interfaces, source pins, and hard blockers. Source-code/IDL byte layouts that are not included in existing repo code or locally installed SDKs remain unverified: do not synthesize or invent them.

## Read order (Codex WITHOUT internet)
1. `../CODEX_START_HERE.md`, then `../R01_BRANCH_RECONCILIATION.md` (R-01 first).
2. `SOURCE_LEDGER.json`: source provenance, exact SHA pins, confidence and coverage. No fetch is required for core facts.
3. `SOLANA_PROTOCOL_DOSSIERS.md`: Jupiter Lend, Kamino, Project 0, Save exclusion.
4. `SUI_PROTOCOL_DOSSIERS.md`: NAVI, DeepBook, Scallop, Cetus, Bucket, Suilend; gRPC/GraphQL warning.
5. `EVM_PROTOCOL_DOSSIERS.md`: Morpho, Euler, Aave, Balancer, Silo, pool-flash sources, aggregator dedup.
6. `PROVIDER_ECONOMICS_AND_SELECTOR.md`: no-new-account filter, fee/capacity/overhead and route-specific decision.
7. `CONTRACT_FACTS.json`: machine-readable exact method names/parameters/known unknowns, not executable code.
8. `GAPS_AND_STOP_CONDITIONS.md`: what is NOT proven.
9. `python offline/verify_bundle.py` from the parent R&D directory; uses Python standard library only and makes ZERO HTTP requests.

## Source coverage
Inspected official docs and/or pinned official source repos for primary/strong-secondary candidates. Every candidate in PROVIDER_CATALOG.json is classified. A documentation URL, an upstream GitHub HEAD SHA or a generic web SDK example is NEVER itself evidence of *current on-chain flash capacity*. Fee, reserve validity, ABI, position-init and execution compatibility remain per-deployment predicates, not provider marketing claims.

## Never do this
- Do not use a website-dependent R-02 implementation or ask Codex to scrape documentation. The offline dossiers are the task contract.
- Never execute demo sign/send code from SDK docs. For flash readers only use governed read APIs.
- Do not auto-enable providers labelled RESEARCH, BLOCKED or any unknown setup/fee/ABI state. Catalog `enabled=false` everywhere.
- Do not use Project 0's zero flash fee to imply no account rent.
- Do not treat Sui legacy JSON-RPC as a permitted transport; gRPC/GraphQL only.
- Do not treat a routing wrapper like Instadapp as newly independent capital if it uses Aave/Morpho/etc.
- Do not infer *all vault/pool balance* is instant flash capacity.
- No signing, sending, wallet initialization, token ATA creation, new margin account, or on-chain receiver deployment in R-02.

## Documentation retrieval playbook (only in environments where the user later enables web)
Fetch legal machine-readable official docs/llms.txt and targeted .md docs into a separate licensed/attributed mirror, hash raw contents, pin npm and Git SHA and compare ABI. Do not overwrite this dated source ledger with a link that redirects to an unrelated version. If licenses prohibit full copying, retain original grounded summaries and external URLs. Offline implementation must function or correctly stop even if that optional mirror is absent.
