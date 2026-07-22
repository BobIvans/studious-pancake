# PR-157 — Isolated signer, finalized settlement and reviewed release gate

This patch adds a side-effect-free gate for the final live/canary release
boundary. It does **not** enable live trading, does not load private keys, does
not sign, and does not submit transactions.

The goal is to make the release decision explicit: a canary is only allowed when
the evidence proves the isolated signer boundary, durable authorization,
settlement reconciliation, hermetic release, sandboxing and operator approvals.

## What this slice adds

- `src/release_path_pr157.py`
  - isolated signer evidence;
  - unified authorization evidence;
  - submission lifecycle evidence;
  - Jito safety evidence;
  - finalized settlement evidence;
  - hermetic release evidence;
  - production sandbox evidence;
  - reviewed canary evidence;
  - `evaluate_release_gate(...)`;
  - `scan_forbidden_live_surface(...)`.

- `tests/test_pr157_release_path_gate.py`
  - 18 focused tests for fail-closed release/canary gating.

## Safety contract

The evaluator blocks when:

- network runtime imports or receives private-key material;
- signer does not parse the exact v0 message itself;
- signer does not verify policy/proof hashes;
- development-memory signer is used for release/canary;
- authorization is caller-constructable, unauthenticated, expired or not durable;
- submission state is unknown or auto-resend is allowed under ambiguity;
- Jito tip evidence is missing, standalone, duplicated or not reviewed;
- finalized `getTransaction(maxSupportedTransactionVersion=0)` evidence is absent;
- settlement reconciliation is missing or negative;
- GitHub Actions, Docker image, wheelhouse or release provenance are not hermetic;
- sandbox controls are incomplete;
- package/config defaults are live-enabled;
- a single environment variable can enable live;
- 72-hour sender-free soak, dual approval, kill switch or rollback evidence is
  absent.

## Non-goals

- No transaction compilation.
- No signing.
- No transaction submission.
- No RPC/Jito/Helius/MarginFi/Jupiter network calls.
- No private key loading.
- No live or canary activation.
- No active runtime rewiring.

## Follow-up integration

Later integration can wire this gate into the reviewed operator release path
after PR-152...156 connect baseline truth, policy/admission, market kernel,
transaction proof and durable paper runtime. Until then, this module is only a
reviewed evidence contract.
