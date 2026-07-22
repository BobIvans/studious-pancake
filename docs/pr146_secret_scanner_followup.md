# PR-146 secret scanner follow-up

This follow-up completes the scanner-hardening slice deliberately removed from PR #157.

## Guarantees

- Secret locator/reference/domain metadata names are not treated as credentials by name alone.
- Runtime code references such as `settings.api_key` and `os.getenv("AUTH_TOKEN")` remain valid.
- Literal fallbacks embedded in lookup expressions are still scanned and fail closed.
- Findings remain value-redacted.
- No live trading, signer, sender, RPC submission, or provider execution behavior is changed.
