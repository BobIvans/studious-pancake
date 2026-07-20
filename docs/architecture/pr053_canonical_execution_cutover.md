# PR-053 canonical execution cutover

## Purpose

PR-053 removes the active execution-domain duality called out by the 2026-07-21 gap audit. The production compiler path must be one Solders v0 domain; older string/positional test shims must not be able to compile into synthetic transaction bytes or prove flash-loan repayment from logs.

## Cutover decisions

- `TransactionPlan` is now a normal frozen dataclass with the canonical field layout only.
- The active `TransactionCompiler` has no `_compile_legacy` dispatch and no synthetic unsigned envelope builder.
- The strict canonical boundary delegates to the same canonical compiler and still rejects any non-canonical envelope if one is supplied from outside the compiler.
- `SimulationRequest.rpc_payload()` no longer strips a synthetic prefix before hash checks.
- `ShadowReconciler` no longer turns a log line containing `repay` into repayment evidence. Repayment must be passed in as state-observed evidence, and a missing observation fails closed.
- `plan_hash()` hashes canonical Solders instruction identities instead of old string-instruction fields.

## Safety / non-goals

- No live sender is enabled.
- No Jito/RPC submission path is changed.
- No external provider, MarginFi, Jupiter, Pump, Phoenix/OpenBook or Kamino promotion state is changed.
- This PR does not wire the paper-shadow runner into discovery/planning; that remains PR-056 through PR-059 scope.
- Compatibility descriptor classes may remain for quarantined tests, but they are not accepted by the active compiler path.

## Focused verification

```bash
python -m pytest tests/execution/test_pr053_canonical_cutover.py -q
python -m compileall -q src/execution tests/execution/test_pr053_canonical_cutover.py
```

Full repository verification should still run through:

```bash
python scripts/verify_repo.py
```
