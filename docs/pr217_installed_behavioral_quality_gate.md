# PR-217 installed behavioral quality baseline gate

This slice implements an additive, side-effect-free acceptance gate for Pass 7
**PR-217 — Installed Behavioral Quality Baseline**.

## Boundary

The gate is intentionally not the full quality-system cutover. It does not
rewrite global CI, mutate existing test suites, run live providers, read secrets,
build wheels or enable sender/live execution. It defines the evidence contract
that a later installed-artifact quality cutover must satisfy.

A passing report still hard-codes:

```text
transaction_signer_allowed=false
sender_allowed=false
live_execution_allowed=false
```

## Covered findings

The validator maps Pass 7 PR-217 findings into deterministic blockers:

- duplicate test hashes cannot be counted as independent evidence;
- unique behavioral-case count must be published;
- line, branch and diff coverage must be enabled and meet thresholds;
- coverage must bind to the installed wheel/hash and composition trace;
- flake8-style debt signals for complexity, unused imports, redefinitions and
  wildcard imports must be enabled;
- formatter targets must be derived from the installed graph, not a manual list;
- active installed graph cannot contain `mypy ignore_errors`;
- active installed graph cannot contain wildcard imports;
- wheel-installed subprocess tests must cover clean env, missing dependency,
  corrupt config, unknown command and interrupted output;
- dependency/config failures must return structured output without raw tracebacks
  unless explicit debug is requested.

## Acceptance added by this PR

- `src/pr217_installed_behavioral_quality_gate.py` defines the immutable
  evidence model and deterministic report.
- `tests/test_pr217_installed_behavioral_quality_gate.py` covers the happy path
  and fail-closed blockers from the audit.

## Why no focused workflow

This PR deliberately does not add a new workflow file. The PR-217 roadmap owns
quality/coverage/format workflow reform, and the current global CI remains the
source of truth for repository compatibility. Local focused verification was
performed before opening the PR.

## Non-goals

This PR does not enable live trading, signing, sender submission, provider calls,
wheel building, dependency lock regeneration, global CI rewrite or production
deployment. It is a reviewable safety contract for the later installed quality
baseline cutover.
