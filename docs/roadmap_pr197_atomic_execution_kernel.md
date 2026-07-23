# Roadmap PR-197 — Atomic Execution and Economic Kernel

This PR starts the consolidated roadmap PR-197 as a sender-free execution and
economic proof boundary.  It deliberately does not import or activate a signer,
transport sender, Jito submit client, live permit, canary or settlement path.

## Scope implemented in this slice

- Adds `src/execution/atomic_kernel_pr197.py`.
- Defines a canonical `ExecutionBinding` joining:
  - rooted/provider state hashes;
  - quote, market and oracle source slots;
  - provider response and route plan hash;
  - MarginFi identity hash;
  - semantic instruction role order;
  - blockhash source slot and expiry height;
  - ALT account/address hashes;
  - final compiled message hash and wire-size evidence;
  - exact simulation identity;
  - integer-only conservative economics.
- Adds a sender-free report that always carries `signed=false`,
  `submitted=false` and `live_enabled=false`.
- Adds a deterministic rejection taxonomy for structure, freshness, simulation,
  identity and economics failures.

## Safety boundaries

The kernel never signs, submits, polls Jito, records a live intent, consumes a
permit or reconciles finality.  A green PR-197 report means only that the final
message and economics are coherent enough for the later sender-free runtime and
evidence gate.  It is not a live-trading approval.

## Roadmap alignment

This maps to the uploaded consolidated audit PR-197 target: build one immutable
sender-free transaction and prove its economic and structural correctness before
any signer/live work.  The larger PR-197 still needs direct integration with the
canonical v0 compiler, exact simulator, durable reservation store and real
MarginFi/Jupiter vectors after PR-195 and PR-196 are accepted.

## Verification target

```bash
python -m pytest tests/test_pr197_atomic_kernel.py -q
python scripts/verify_repo.py
```

The new Python files are registered in `config/format_targets.txt` for the
repository-wide formatter baseline.
