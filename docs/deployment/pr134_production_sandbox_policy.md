# PR-134 — Production container sandbox and deployment policy

This PR adds the first reviewable production sandbox profile for the runtime
container. It is intentionally separate from the Dockerfile and image smoke test:
a non-root image is necessary, but it does not prove the production deployment
cannot write arbitrary paths, gain privileges, or contact unapproved endpoints.

## Included artifacts

- `deploy/production/docker-compose.sandbox.yml` — compose profile with the
  minimum production controls for local paper/live-review rehearsal.
- `deploy/production/container_sandbox_policy.json` — machine-checkable policy
  contract for PR-134 controls.
- `deploy/production/seccomp-runtime.json` — explicit seccomp profile stub with
  `SCMP_ACT_ERRNO` as the default action.
- `deploy/production/runtime.env.example` — disabled-live defaults and empty
  provider credential placeholders for secret-manager mounting only.
- `scripts/validate_deployment_sandbox.py` — standard-library validator used by
  tests and reviewers.

## Required controls

The sandbox profile requires:

- fixed non-root user `10001:10001`;
- read-only root filesystem;
- writable state only through approved volumes or tmpfs;
- tmpfs for `/tmp` and `/run/flashloan-bot`;
- `cap_drop: [ALL]`;
- `no-new-privileges:true`;
- explicit seccomp and AppArmor profile references;
- PID, memory, CPU, `nofile` and `nproc` limits;
- Docker secret mount for runtime configuration;
- healthcheck bound to the real runtime health endpoint;
- live/Jito/Kamino liquidation defaults hard-disabled;
- explicit egress-policy requirement and signer/network split requirement in the
  policy manifest.

## Non-goals

This PR does not enable live submission, change sender behavior, change signer
behavior, publish an image, or claim that the compose file is the final
production orchestrator. Kubernetes/systemd equivalents should consume the same
`container_sandbox_policy.json` contract in follow-up work.

## Reviewer checklist

Before any production-style run, the operator must replace
`FLASHLOAN_RUNTIME_IMAGE` with a reviewed digest-pinned image reference and
provide credentials through Docker secrets or a secret manager outside the
repository. The compose profile must not be weakened with `privileged`, host
network/PID/IPC, capability additions, unconfined seccomp/AppArmor, or arbitrary
host mounts.
