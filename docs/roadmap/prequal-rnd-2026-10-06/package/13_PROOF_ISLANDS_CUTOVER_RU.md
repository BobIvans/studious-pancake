# Proof Islands → Runtime Authorities

A proof module is useful only if an authority consumes it.

For each proof/gate classify:
- `RUNTIME_REQUIRED`: runtime bootstrap checks exact artifact.
- `RELEASE_REQUIRED`: release bundle checks exact artifact.
- `CAMPAIGN_REQUIRED`: campaign runner checks exact artifact.
- `DIAGNOSTIC_ONLY`: never allowed to satisfy readiness.
- `SUPERSEDED`: delete from active capability graph.

Build a graph:
`proof artifact → verifier → authority owner → runtime/release decision`.

Any artifact with no path to an authority is evidence debt, not readiness.
