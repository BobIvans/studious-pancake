# PR-200 production cutover operations gate

This PR-200 continuation adds an offline evidence gate for the operational
cutover part of the production roadmap. It deliberately does not deploy,
promote, roll back, sign, submit or enable live trading.

The gate checks that the already added PR-200 production sandbox manifest is
clean, then requires explicit evidence for:

- signed release artifact binding;
- readiness/liveness separation;
- backup/restore rehearsal;
- drain-only rollback;
- legacy live-surface quarantine;
- required SLO budgets under fault load;
- required fault-injection drills.

`validate_pr200_cutover_evidence()` returns a deterministic report with stable
diagnostic codes. Both `live_capability_allowed()` and
`cutover_capability_allowed()` return `False` by construction.

This is a reviewable acceptance-boundary scaffold. Real production cutover
still requires externally captured hashes, signed release manifests, real
backup/restore artifacts, real chaos results and operator approval after the
earlier roadmap prerequisites are accepted.
