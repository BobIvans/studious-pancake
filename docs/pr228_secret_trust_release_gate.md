# PR-228 — secret trust, signed state, retention and release identity gate

This checkpoint starts **PR-228** from the Pass 8 + Pass 9 roadmap.

It is an offline, sender-free acceptance contract. It does not read secret files,
decrypt credentials, publish management state, sign state, purge outbox evidence,
run release promotion, access private keys or enable live trading.

## Scope

The roadmap assigns PR-228 ownership of findings **F-424…F-443** and
**F-496…F-500**.

This gate covers the required PR-228 trust/control-plane invariants:

- deny-by-default secret roots and provider registry;
- atomic reveal/revoke/max-use/lease/audit protocol;
- safe file acquisition with no-follow single-open semantics;
- stable inode/size/mtime/digest verification before and after reads;
- byte limits and symlink/content swap detection;
- secret versions derived from exact bytes instead of caller input;
- scoped handle/buffer delivery rather than durable immutable string reveal;
- persistent credential lifecycle, rotation and revocation state;
- external state trust anchor that the runtime cannot self-generate;
- strict nested signed-state and readiness schemas;
- verified proxy identity rather than self-asserted booleans;
- management auth rate limit, lockout and audit counters;
- supervisor-derived liveness and readiness;
- crash-safe state publication through temp write, file fsync, atomic rename and
  directory fsync;
- retention purge only after verified WORM receipt and trusted cutoff;
- exact release identity bound to installed wheel, image, config and trust bundle.

## Added files

- `src/pr228_secret_trust_release_gate.py`
- `tests/test_pr228_secret_trust_release_gate.py`
- `docs/pr228_secret_trust_release_gate.md`

## Focused verification

```bash
python -m py_compile src/pr228_secret_trust_release_gate.py
PYTHONPATH=. python -m pytest -q tests/test_pr228_secret_trust_release_gate.py
```

## Safety boundary

A passing report allows only:

```text
secret_trust_review_allowed=true
secret_reveal_allowed=false
management_ready_allowed=false
release_ready_allowed=false
operational_paper_ready_allowed=false
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
```

This means the PR is still not a runtime secret delivery cutover, management
readiness promotion, release qualification or live boundary.

## Remaining physical PR-228 work

The next slices must wire this contract into the active secret policy, file
secret reader, credential lifecycle registry, signed-state readers,
management/readiness server, state publication helpers, retention ledger and
release identity manifest. Those changes must preserve the rollback protocol:
previous trust/config/state generations can be restored without resurrecting
revoked credentials or deleting evidence before verified WORM receipt.
