# PR-176 — Hermetic qualification environment

This PR starts the snapshot-11 PR-176 workstream.

## Added

- `src/qualification_pr176.py` defines the hermetic qualification contract.
- `scripts/qualify_release.py` prints a deterministic qualification manifest.
- `scripts/qualify_release.sh` is the one-command wrapper.
- `tests/test_pr176_hermetic_qualification.py` covers profile isolation,
  dependency closure and manifest identity.

## Safety

Default execution is non-mutating:

```bash
bash scripts/qualify_release.sh
```

It does not create a venv, install packages, call the network or execute test
profiles. `--execute` is explicit and runs only selected profile commands.

## Remaining PR-176 work

Later slices should add hashed offline wheelhouse materialization, raw JUnit
capture, repeated clean-run comparison, source/wheel parity evidence and signed
provenance.
