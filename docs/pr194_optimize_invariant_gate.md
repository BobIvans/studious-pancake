# PR-194 pass-4 optimize-mode invariant gate

This slice strengthens the PR-194 trusted build/package/composition foundation without enabling paper or live execution.

## Why

The pass-3 production-readiness audit requires PR-194 to prove that validation and security invariants still hold when Python runs with `-O` / `PYTHONOPTIMIZE=1`. Python removes `assert` statements in optimized mode, so production-critical checks must use explicit exceptions and fail-closed gates instead of runtime `assert`.

## What is enforced

`scripts/verify_pr194_optimize_invariant.py` emits deterministic `pr194.optimize-invariant-gate.v1` evidence and fails non-zero when a declared production-critical path either:

- contains an `assert` statement that would disappear under optimized execution; or
- is missing from the repository tree.

The gate intentionally ignores `tests/`, build outputs and cache directories because tests should continue to use normal pytest assertions.

## Default checked surface

The default target set is intentionally narrow and additive so this PR does not conflict with the parallel PR-194 required-control manifest slice:

```text
arb_bot.py
src/production_surface.py
scripts/package_smoke.py
scripts/verify_repo.py
```

Later PR-194 slices can widen the checked surface or wire this verifier into full repository verification after the active production composition-root manifest lands.

## Safety boundary

This PR remains sender-free and offline:

- no live trading;
- no signer or private-key loading;
- no transaction construction or submission;
- no provider/RPC/Jito/Helius/MarginFi/Jupiter network calls;
- no paper/live readiness claim.

The implementation helper lives under `scripts/` so the gate can run in CI without expanding the installed runtime/package surface.

## Focused verification

```bash
python scripts/verify_pr194_optimize_invariant.py --json
python -m pytest -q tests/test_pr194_optimize_invariant_gate.py
```
