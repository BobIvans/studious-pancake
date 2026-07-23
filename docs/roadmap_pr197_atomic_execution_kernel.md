# Roadmap PR-197 — Atomic Execution and Economic Kernel

This PR is the consolidated roadmap PR-197 sender-free execution and economic
proof boundary. It deliberately does not import or activate a signer, transport
sender, Jito submit client, live permit, canary or settlement path.

## Scope implemented in this slice

- Adds and hardens `src/execution/atomic_kernel_pr197.py`.
- Defines a canonical `ExecutionBinding` joining:
  - rooted/provider state hashes;
  - quote, market and oracle source slots;
  - provider response and route plan hash;
  - MarginFi identity hash;
  - semantic instruction role order;
  - decoded semantic account-effect evidence;
  - blockhash source slot and expiry height;
  - ALT account/address hashes;
  - final compiled message hash and wire-size evidence;
  - exact simulation identity;
  - integer-only conservative economics.
- Adds a sender-free report that always carries `signed=false`,
  `submitted=false` and `live_enabled=false`.
- Adds a deterministic rejection taxonomy for structure, semantic account
  effects, freshness, simulation, identity and economics failures.

## Semantic firewall hardening

The kernel no longer treats a program-id allowlist as enough evidence. Every
compiled instruction must have decoded semantic account-effect evidence bound by
hash to the final message. The firewall rejects:

- System/SPL account effects that can move value or authority, including
  transfer, approve, revoke, set-authority, delegate, mint, burn, freeze and
  thaw actions;
- unsafe token-account close operations unless they are exact
  `cleanup.close_ata` actions returning lamports to the payer;
- Token-2022 effects unless the policy explicitly carries an attested extension
  hash;
- effects whose role is not present in the canonical instruction sequence;
- missing decoded MarginFi/Jupiter effects for the required flash-loan bracket;
- wallet writable deltas above the explicit semantic budget.

This keeps PR-197 as a sender-free proof kernel while making it much closer to
the roadmap acceptance gate: semantic safety is based on decoded economic
effects, not just on allowed program ids.

## Economic fee semantics

`rpc_total_message_fee_lamports` is the authoritative fee total for the exact
final message. The base and priority fields are explanatory components and must
sum to that RPC total; they are never added again as a second network-fee path.
This prevents the `getFeeForMessage` double-counting failure mode.

## Safety boundaries

The kernel never signs, submits, polls Jito, records a live intent, consumes a
permit or reconciles finality. A green PR-197 report means only that the final
message, decoded account effects, simulation identity and economics are coherent
enough for the later sender-free runtime and evidence gate. It is not a
live-trading approval.

## Roadmap alignment

This maps to the uploaded consolidated audit PR-197 target: build one immutable
sender-free transaction and prove its economic and structural correctness before
any signer/live work. The larger PR-197 still needs direct integration with the
canonical v0 compiler, exact simulator, durable reservation store and real
MarginFi/Jupiter vectors after PR-195 and PR-196 are accepted.

## Verification target

```bash
python -m pytest tests/test_pr197_atomic_kernel.py -q
python scripts/verify_repo.py
```
