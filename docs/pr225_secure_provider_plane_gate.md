# PR-225 secure provider, quote and rooted discovery plane gate

This is the first safe Pass 8/9 **PR-225** implementation slice. It turns the
roadmap acceptance boundary into a deterministic, offline evidence contract for a
sender-free provider plane.

## Scope

Added module:

- `src/pr225_secure_provider_plane_gate.py`

The gate validates already-materialized evidence for:

- canonical provider contracts;
- one owned hardened transport authority;
- deny-by-default host/DNS/TLS/redirect/response-budget/redaction policy;
- retry semantics with a single total deadline and no unsafe non-idempotent POST
  retry;
- durable account-wide credential quota;
- raw provider response provenance before normalization;
- strict quote request/domain identity;
- guaranteed-output based deterministic discovery selection.

Added tests:

- `tests/test_pr225_secure_provider_plane_gate.py`

## Safety boundary

This PR does **not** call providers, Solana RPC, Helius, Jupiter, MarginFi,
Kamino, OKX, OpenOcean, Odos, Jito, a signer or a sender. It does not construct,
sign, simulate or submit transactions and does not enable paper/live promotion.

A passing report still returns:

```text
provider_network_allowed=false
executable_candidate_allowed=false
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
```

## Verification

```bash
python -m py_compile \
  src/pr225_secure_provider_plane_gate.py \
  tests/test_pr225_secure_provider_plane_gate.py

PYTHONPATH=. python -m pytest -q tests/test_pr225_secure_provider_plane_gate.py
# 8 passed
```

## Remaining physical PR-225 work

This gate is not the full provider-plane cutover. Follow-up implementation must
wire the contract into the installed sender-free composition root, replace active
provider clients with the reviewed transport owner, produce real redacted
provenance from configured endpoints, retire incompatible Jupiter/generic parser
generations, and run hostile provider, DNS rebinding, duplicate/retry and
multi-process quota qualification against the installed artifact.
