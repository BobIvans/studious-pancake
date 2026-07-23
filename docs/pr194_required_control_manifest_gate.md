# PR-194 pass-3 required-control manifest gate

This slice strengthens the PR-194 foundation without enabling paper/live
execution.

## Why

The production-readiness pass-3 audit keeps PR-194 as the build, package,
composition and CI foundation boundary. The audit specifically says PR-194 must
prove that the installed artifact is the program under test, that required
controls are reachable from the production composition root, and that blocked or
misconfigured paper-readiness commands cannot return success.

This pass therefore moves the first required-control list into the packaged
production-surface manifest and adds an offline verifier that can run in the
normal repository verification chain.

## What is enforced

`scripts/verify_pr194_required_controls.py` emits
`pr194.required-control-gate.v1` evidence and fails non-zero when:

- live capability is weakened;
- the sender-free runtime contract is weakened;
- a console entrypoint target is not bound to a required control;
- a required control is not included in the wheel-member authority;
- a required control source file is missing;
- a blocked/misconfigured CLI contract is missing or weakened.

The verifier is deliberately offline. It does not call RPC, Jupiter, MarginFi,
Helius, Jito, a signer, or any wallet loader.

## Manifest additions

`src/resources/production_surface_manifest.json` now declares:

- all installed console entrypoints, not only the primary CLI and healthcheck;
- `required_controls` for the PR-194 composition/root inspection surface;
- `blocked_command_contracts` that require non-zero exit semantics for blocked
  paper/readiness checks.

`src.production_surface` exposes typed helpers for those manifest sections so
package smoke, CI scripts and later PR-194 slices can share one authority.

## Verification path

`python scripts/verify_repo.py` now runs the PR-194 required-control gate after
package smoke. This keeps the gate close to the installed-artifact boundary and
before broader compile/pytest checks.

Focused verification:

```bash
python scripts/verify_pr194_required_controls.py --json
python -m pytest -q tests/test_pr194_required_control_manifest.py
python scripts/verify_repo.py --skip-dependency-audit
```

## Safety boundary

This PR remains sender-free:

- no live trading;
- no signer or private-key loading;
- no transaction construction or submission;
- no provider/RPC/Jito network calls;
- no paper/live readiness claim.

It is a foundation gate that later PR-194 slices can extend into full installed
wheel import/public-export closure, hermetic dependency evidence and
source/wheel parity.
