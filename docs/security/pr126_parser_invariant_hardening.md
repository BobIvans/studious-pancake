# PR-126 parser invariant hardening

PR-126 starts the roadmap item **Parser invariant hardening, error taxonomy and fuzz/property/mutation suite**.

## Why this exists

Python removes `assert` statements when code is executed with `python -O`. Any production parser, protocol or security validation expressed as `assert` can therefore disappear in optimized mode. PR-126 introduces assertion-free helpers and regression tests so validation remains active regardless of optimization flags.

## Scope in this slice

- Add a shared PR-126 error taxonomy:
  - provider business error;
  - transport error;
  - schema drift;
  - protocol rejection;
  - programmer invariant violation;
  - security violation.
- Add `require_invariant(...)` as the assert-free validation primitive.
- Add bounded JSON-object parsing for hostile external/provider payloads.
- Add an AST scanner for:
  - production `assert` debt;
  - broad `except Exception` / bare `except` debt unless explicitly justified with `pr126: allow-broad-except`.
- Add optimized-mode regression coverage proving that `python -O` cannot disable `require_invariant(...)`.
- Add deterministic fuzz/property-style cases for malformed JSON, non-object top-level values, invalid UTF-8 and parser budget rejection.

## Non-goals

This PR does not convert every existing parser or protocol decoder in one step. Follow-up PRs should migrate active external-contract, token, MarginFi and instruction parser boundaries to this helper, retain sanitized crash fixtures and wire the AST scanner into the repository-level quality gate once legacy debt is explicitly triaged.

## Acceptance covered by this slice

- Disabling Python assertions cannot weaken the new PR-126 validation helper.
- Parser failures carry a stable category instead of leaking raw hostile payload contents.
- Assert and broad-exception debt are machine-detectable and fail closed through `assert_no_parser_invariant_debt(...)`.
