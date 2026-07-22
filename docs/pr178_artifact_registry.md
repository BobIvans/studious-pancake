# PR-178: Atomic signed artifact registry and filesystem trust boundary

This slice hardens the active decision model artifact loader and publisher. It
addresses the reproduced snapshot-11 findings around `latest.json` path escape,
self-checksum trust, non-finite JSON, coefficient/vector truncation and unsafe
file modes.

## Runtime changes

- `latest.json` is now parsed as a strict pointer object with exactly
  `artifact` and `checksum`.
- The pointer artifact must be a relative basename inside the model directory.
  Absolute paths, `../`, symlinks and hardlinks fail closed.
- The pointer checksum must match the loaded artifact checksum.
- Artifact JSON rejects duplicate keys and `NaN` / `Infinity`.
- Model artifacts are schema-checked before recommendation:
  - exact artifact and feature-spec versions;
  - exact known keys;
  - finite numeric values;
  - exact `feature_order` / `coefficients` cardinality;
  - exact category and numeric feature dimensions.
- Training and evaluation outputs use restrictive `0600` files, same-directory
  temporary writes, `fsync`, atomic replace and parent-directory `fsync`.
- Inference uses `zip(..., strict=True)` after schema validation.

## Safety boundary

This PR does not change model mathematics, ranking thresholds, live trading,
signing, sending, RPC, Jito, MarginFi or Jupiter behavior. It only constrains
local artifact publication and loading before an artifact can influence advisory
ranking.

## Follow-up work

The full PR-178 programme should still add a generalized signed
content-addressed registry for datasets, evidence, readiness reports, release
artifacts and policy snapshots. This slice closes the active decision-model
trust boundary first because it is the reproduced runtime-facing escape.
