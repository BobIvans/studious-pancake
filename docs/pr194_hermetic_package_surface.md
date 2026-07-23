# PR-194 — hermetic package and image boundary slice

This branch implements the first PR-194 production-surface slice from the
consolidated roadmap. It focuses on the highest-risk package/image parity
failure: Docker must build the same sender-free wheel boundary that package
smoke validates.

## Scope

The PR introduces `src/resources/production_surface_manifest.json` as the
single machine-readable source of truth for:

- required production wheel members;
- installed console entrypoints;
- exact forbidden legacy/live module files;
- forbidden package prefixes;
- forbidden import names;
- development/analytics imports banned from the runtime image.

`setup.py`, package smoke and image smoke now consume that same manifest instead
of maintaining independent forbidden-module lists.

## Docker boundary fix

The builder stage now copies `setup.py` before `pip install .`. That preserves
`ProductionBoundaryBuildPy`, which removes the quarantined modules from the
installed runtime wheel.

Without this, a Docker-style build context can include modules that the normal
wheel smoke assumes are absent.

## Runtime safety boundary

This PR does not add any signer, sender, Jito submission, live trading path,
or external provider activation. It only tightens the artifact boundary and
verifies that the shipped package/image remain sender-free and live-disabled.

## Verification

Focused verification covers:

```text
python -m black --check setup.py scripts/package_smoke.py src/production_surface.py tests/test_pr194_production_surface_manifest.py
python -m mypy src/production_surface.py
python -m pytest -q tests/test_pr194_production_surface_manifest.py
python scripts/package_smoke.py
python -m compileall -q setup.py scripts/package_smoke.py src/production_surface.py
```

The general repository CI still owns the full package smoke and Docker image
smoke. Because `scripts/image_smoke.sh` now checks the manifest-driven forbidden
import boundary inside the running container, a green image smoke proves the
runtime image does not expose the quarantined production modules.
