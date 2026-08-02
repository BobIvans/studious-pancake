# MPR-TD-02 current-main baseline

- **Accepted base:** `f837394449b3921c8f502543aaf3f2694274093a`
- **MPR-TD-01:** present as merge commit `f837394` (GitHub PR 458).
- **Scope:** installed `src` packages; `src/ingest` and `src/execution/senders` remain excluded/quarantined by the package manifest.
- **Open-PR inspection:** GitHub open pull requests were inspected on 2026-08-02. Overlaps include provider/data-plane PRs 440/447, persistence PR 443, runtime supervision PR 298, installed product PR 411, and paper/shadow PRs 428/275. No branch was merged blindly; this change establishes semantic owners over the accepted base.
- **Inventory:** machine-readable exception boundaries, retry/cancellation observations, tests, workflows, and installed-wheel path are recorded in `config/mpr_td_02_*`.
- **Existing behavior:** broad catches and relative timeouts are distributed across active modules; retry/error strings have no single registry; the persistence async writer contains the only located active shield.
- **Verification baseline:** CI is highly duplicated, and no authoritative property, mutation, fuzz, flake, or profile manifest exists.
- **Safety:** sender packages remain excluded and live authorization remains outside this work.

The inventories deliberately label findings rather than asserting migration. Items not migrated are blockers in final evidence.
