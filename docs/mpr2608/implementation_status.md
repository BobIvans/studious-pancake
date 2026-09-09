# MPR-2608 — isolated signer + submission boundary + 2610A

Base: `main@68788d7f7f7da8a2e03b170f93c48af7421ee805` (merged MPR-2601 / PR #472).

## Ownership / anti-duplication

| Requirement | Observed owner | MPR-2608 action |
| --- | --- | --- |
| runtime/lifecycle/capital fencing | accepted MPR-2601 | REUSE ONLY; no second runtime/economic ledger |
| MPR-2602 provider checkpoint | draft PR #473 | prerequisite; not treated as accepted |
| human intervention authority | MPR-2603 scope | CONSUME; no new approval UI/format |
| broad production closure / W08 | PR #475 / MPR-2604 | CONSUME_AND_VERIFY; no second canary controller |
| protocol evidence | MPR-2605 | CONSUME; no provider qualification duplicated here |
| shadow qualification | MPR-2607 | prerequisite only |
| isolated signer IPC, atomic permit+intent, dispatch uncertainty, 2610A | MPR-2608 | OWNED HERE |
| activation and canary budgets | MPR-2609 | OUT OF SCOPE |
| complete realized-PnL settlement | MPR-2610 | OUT OF SCOPE except minimum 2610A |

## Implemented in this slice

`isolated_signer_service/src/flashloan_isolated_signer/mpr2608.py` adds a dependency-light, default-off qualification implementation:

- strict framed Unix-domain-socket IPC with a single `sign_approved_solana_transaction` method;
- duplicate-key/unknown-field/size/deadline/service-generation rejection;
- exact unsigned-message SHA-256 binding and an independent validator hook executed inside the signer process;
- narrow `SigningBackend` protocol that exists only in signer scope; there is no generic `sign(bytes)` API;
- bounded receipt containing signature, signed-wire bytes and hashes but no key material;
- one SQLite `BEGIN IMMEDIATE` transaction for one-shot permit consumption + durable intent creation;
- durable pre-network dispatch marker that moves the attempt to `ISSUED_UNKNOWN` before any external effect is permitted;
- ACK classification that remains non-final;
- minimum 2610A states and capital-hold behavior: unknown/ACK/pending-economics keep the hold; finalized failure or fully settled outcome may release it;
- idempotent replay for the exact same durable intent and conflicts for changed semantic payloads.

The helper store is explicitly not a new production economic authority. Integration must map the atomic operation into the accepted canonical lifecycle/capital writer before activation.

## Deliberately not implemented / not enabled

- no production private key, seed, env/file locator or user trading credential;
- no production KMS/HSM/keychain adapter evidence;
- no RPC/Jito sender or network call;
- no automatic RPC↔Jito fallback;
- no transaction rebuild/re-sign retry on unknown outcome;
- no canary/live activation;
- no multi-transaction Jito bundle path;
- no claim of exactly-once network delivery;
- no full realized PnL decoder;
- no merge automation.

`MPR2608_COMPILE_ENABLED = False` remains explicit. Production secret backend and transport qualification are `BLOCKED_EXTERNAL/BLOCKED_INTEGRATION`, not fabricated as passing evidence.

## Focused regressions

`tests/test_mpr2608_isolated_signer_submission.py` covers:

1. atomic permit+intent replay;
2. changed-message/semantic replay denial;
3. two-consumer race on one permit;
4. dispatch marker as the uncertainty linearization point;
5. ACK != finality and capital hold persistence;
6. finalized-success pending economics;
7. finalized failure release path;
8. confirmed != finalized;
9. strict IPC method/schema rejection;
10. independent signer validation and signed-wire receipt verification;
11. signer expiry/service-generation denial.

No test uses real trading credentials. The fixture backend returns deterministic fake signed bytes and is not a Solana production signer.

## Completion classification

This branch is an implementation checkpoint for MPR-2608, not a `production_ready` declaration. The physical boundary and restart-safe state machine are suitable for offline qualification; actual production signing, external secret backend conformance, transport conformance, installed-artifact evidence, canonical lifecycle integration, and MPR-2609 activation remain blocked until their owners and environments are accepted.
