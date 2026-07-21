# PR-101 — MarginFi complete protocol evidence boundary

PR-101 is the next MarginFi promotion gate after the verified executable hash.
It does **not** make MarginFi live-ready and does not assemble, sign or submit
transactions.

## Goal

The repository may only treat MarginFi as a sender-free shadow execution
dependency after all decisive evidence families are materialized and reviewed:

```text
verified source and executable pin
→ canonical IDL/layout artifact
→ SDK-generated account vectors
→ SDK-generated flash-loan instruction vectors
→ read-only mainnet RPC relationship evidence
→ flash-loan account meta/order proof
→ Token and Token-2022 proof
→ conservative repayment arithmetic
→ deployment metadata provenance
→ human review and signature
```

## Current state

The checked-in `src/resources/marginfi_pr055.json` deliberately remains blocked.
The verified build hash is preserved, but IDL, SDK vectors, RPC evidence,
flash-loan meta proof, Token-2022 proof, repayment math and human review are
still `null`/`false`.

`evaluate_marginfi_complete_evidence()` therefore reports stable blockers such
as:

```text
DECISIVE_FIELD_MISSING:idl.sha256
DECISIVE_FIELD_FALSE:promotion.human_reviewed
PR101_SCHEMA_MISMATCH
```

## Safety boundary

- `shadow_execution_capable` is true only when every decisive field is present
  and true.
- `live_execution_allowed` is always false.
- Any `live_allowed=true` field is a blocker even when the rest of the manifest
  is otherwise complete.
- PR-101 does not import senders or signers.
- PR-101 does not bypass PR-099 admission or PR-100 package boundary work.

## Suggested verification

```bash
python -m pytest tests/test_pr101_marginfi_complete_protocol_evidence.py -q
python scripts/verify_repo.py --skip-dependency-audit
```

## Remaining real evidence work

To move from blocked to `shadow-execution-capable`, a future patch must commit
real evidence artifacts under review, replace the decisive `null`/`false` fields
with hashes/proofs, and keep `live_allowed=false`.
