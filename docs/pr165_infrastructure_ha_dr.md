# PR-165 — Enforced infrastructure isolation, HA and disaster recovery

This PR starts roadmap PR-165 as a low-conflict, additive evidence gate.

The production-readiness audit defines PR-165 as the point where sandbox, backup,
failover and disaster recovery policies become technically enforced rather than
only declared.  This slice does not configure infrastructure directly and does
not enable live execution.  It creates the review contract that future
deployment work must satisfy before live/canary claims can be accepted.

## Implemented slice

- Adds `src/infrastructure_ha_dr_pr165.py`.
- Adds a deterministic `InfrastructureHaDrEvidence` model.
- Requires enforced default-deny egress through an accepted mechanism.
- Rejects Compose-style unrestricted bridge networking without a real firewall
  or equivalent enforcement artifact.
- Requires real AppArmor and seccomp profile evidence.
- Requires runtime/signer trust-zone separation.
- Requires authenticated IPC and no general signer internet.
- Requires encryption at rest for lifecycle DB, evidence, backups, operator
  approvals and sensitive alert state.
- Requires remote immutable encrypted backups outside the runtime host/volume.
- Requires measured RPO/RTO targets.
- Requires active/passive fencing, single active runtime and split-brain drills.
- Requires provider/RPC failover to preserve genesis, rooted-state, quota and
  effective-policy evidence.
- Requires deployment truth hashes for the actual deployed image, profiles,
  capabilities, mounts, resources, secret mounts and network topology.
- Keeps `live_claim_allowed = false`.
- Keeps `sender_submission_allowed = false`.

## Safety / non-goals

- No live trading.
- No sender or signer path.
- No network, KMS, backup, Docker, Kubernetes, firewall or object-store mutation.
- No edits to workflows, Dockerfile, compose files or dependency locks.
- No claim that production infrastructure is already enforced.

## Follow-up integration

A later implementation can feed this contract from actual deployment evidence:
AppArmor/seccomp profile hashes, firewall or NetworkPolicy manifests, observed
runtime capabilities, encrypted remote backup reports, restore drills, fencing
tokens, provider failover drills and signed release metadata.
