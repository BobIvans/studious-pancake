# R02-CAP-UNBLOCK / R03-HANDOFF — pinned SDKs and local decoder references

Updated 2026-10-08. Base code audited: `main@8e222fcddb7fd3bc6e5720d9585e5d5903812294` (PRs #584/#585 merged).

**Documentation/reference-only PR.** No new live read, no positive capital edge, no account creations, no signed/submitted transactions, no deployed contracts, no permission to trade. Neither the source-code reference snapshots nor the structural probe below equal a deployed-state qualification. The *current* GitHub and on-chain state must be verified anew by Codex.

## Start
1. `CODEX_START_HERE.md`: exact task order, narrow PR scopes.
2. `MASTER_CONTEXT.md`: actual state and previous evidence.
3. `R02_UNBLOCK_MATRIX.md`: Jupiter, Kamino, NAVI, Project0 independent blockers and lowest-cost route to resolve them.
4. `offline/VENDOR_MANIFEST.json`: **19 verbatim SDK files** (Git blob SHA checks), compatible published source versions plus licenses. Open `offline/vendor/{navi,kamino,p0}`; no web browser or fetching documentation required.
5. `offline/jupiter_token_reserve_layout.json`: **exact published IDL-derived fixed fields** with sizes/offsets and discriminator.
6. `offline/kamino_reserve_prefix_layout.json`: audited SDK-defined reserve **prefix only**; fee+limits need the full vendored SDK decoder.
7. `offline/navi_sdk_bridge_facts.json`, `offline/p0_public_discovery_facts.json`: current source behavior, uncertainties and public-address-only mode.
8. `R02_ACCEPTANCE.md`, `R03_SHADOW_BUILDERS.md`, `P0_PUBLIC_ACCOUNT_PATH.md`, `LICENSE_AND_PROVENANCE.md`.

Run from root:
```bash
python docs/roadmap/r02-capacity-recovery-2026-10-08/offline/verify_offline.py
python -m unittest discover -s docs/roadmap/r02-capacity-recovery-2026-10-08/offline -p "test_*.py"
```

**Never require Codex to browse missing docs.** All listed source files and ABI facts are local. If the targeted decoder depends on further specific source or deployed state not contained here, report named `MISSING_DEPLOYED_ABI` or `MISSING_CHAIN_STATE` with exact required source, no assumptions. No user wallet input is needed for Jupiter, Kamino or NAVI. P0 read-only protocol/bank discovery can proceed without a wallet; **wallet eligibility requires a separate optional public-authority/account input**.
