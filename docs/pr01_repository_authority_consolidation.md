# PR-01 — Repository queue and authority consolidation

This change creates the first enforceable numeric-roadmap authority boundary.

## Contract

`config/runtime_authority_map.json` is the repository source of truth and
`src/resources/runtime_authority_map.json` is the installed-wheel mirror.

The contract separates:

- the installed console-script owner (`src/cli_pr189.py`);
- the canonical runtime CLI implementation (`src/cli.py`);
- one declared owner for each production concern;
- authoritative lifecycle stores from diagnostic-only journals;
- evidence-schema owners and packaged mirrors;
- the PR-01 through PR-10 dependency sequence;
- active roadmap branches from GitHub review candidates;
- quarantined or not-packaged historical implementations.

An open pull request is never a runtime authority merely because it exists.
Authority changes require a reviewed merge that updates this map and all
dependent package/capability contracts in the same change.

## Queue snapshot

The queue section records open GitHub PRs observed on 2026-07-23 and maps them
to the new numeric programme. Superseded entries are explicitly marked and
cannot become active owners.

This PR does not automatically close other pull requests. Closure remains a
reviewed repository mutation after unique negative tests are preserved.

## Verification

`python scripts/validate_authority_map.py` checks:

- one owner per concern;
- at most one active branch per numeric vertical;
- PR-08 through PR-10 remain hard-disabled;
- declared owner and legacy paths exist;
- `pyproject.toml` exposes the declared installed entrypoint;
- the capability launcher belongs to the declared delegation chain;
- repository and packaged authority/capability mirrors are identical.

The aggregate repository verifier and wheel smoke run this contract.

## Baseline reconciliation

Current `main` already includes the numeric-looking Solana Program ID YAML fix
and the A3 regression update to the canonical A2 report shape. The PR-01 branch
was rebuilt after those changes landed, so neither correction appears in this
PR's effective diff.

## Safety

No live trading, signer access, wallet loading, transaction construction or
submission is enabled. Product state remains `not-production-ready`.
