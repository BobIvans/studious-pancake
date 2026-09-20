# PR-010 — final product-graph and readiness audit (Wave 6, merge last)

PR-010 is an integration audit, not another implementation island. It may merge
only after PR-001 through PR-009 are ancestors of its base, in that exact order.
The gate in `src/pr010_final_readiness.py` therefore fails closed when any prior
merge is missing, ancestry is unverified, or a stale/open PR branch remains.

Readiness requires a graph produced from the installed wheel, clean-install
source/wheel parity, one composition root and one product authority, and verified
release-bundle and qualification-log byte hashes. Superseded proof islands must
be removed rather than listed as additional evidence.

Production debt is closed only when its entry points to a non-placeholder digest
and a materialized, independently verified artifact path. A closure declaration
without that evidence is reported as open debt and remains a release blocker.
This makes a `blocked` result an honest final readiness state, not a failed audit.

At this branch point only PR-001 through PR-004 are present in Git history.
Consequently PR-010 **must not be represented as ready or merged yet**; PR-005
through PR-009 and their release evidence remain mandatory inputs.
