# MPR-20 — Typed configuration, credential lifecycle and sandbox gate

This checkpoint starts **MPR-20: Typed configuration, credential lifecycle and enforceable deployment sandbox** from the V9 roadmap.

It is a side-effect-free fail-closed acceptance contract. It does not read environment variables, parse local config files, load secrets, inspect Docker, open signer IPC, contact RPC/Jito/providers, or enable live execution.

## Scope captured by the gate

MPR-20 owns the startup trust boundary:

- one versioned typed configuration contract for CLI, container and signer;
- fail-closed unknown `FLASHLOAN_*` variables, clusters and secret schemes;
- bounded no-follow config loading with duplicate-key, NaN and YAML-bomb rejection;
- HTTPS/WSS-only RPC, rooted/finalized commitment and registry-bound program identity;
- startup RPC doctor through the hardened provider transport;
- signer secrets resolved only in the isolated signer process;
- content/generation-bound secrets with rotation, revocation, monotonic lease and maximum-use CAS;
- Docker secret file consumption and removal of obsolete variable names;
- UID 10001 volume readiness for DB/log/archive paths;
- loaded AppArmor and seccomp profiles on the target host;
- SQLite WAL/fsync syscall allowance and denied-syscall probes;
- enforceable deny-by-default egress through explicit proxy/firewall and destination allowlist;
- value-level diagnostic and crash-log redaction.

## Dependency boundary

MPR-20 depends on accepted MPR-18 installed artifact truth. Missing MPR-18 evidence returns `MPR20_MPR18_NOT_ACCEPTED`.

This PR may be reviewed before the full cutover, but readiness remains blocked until MPR-18's installed artifact, release-set, surface trace and signer-split manifests are materialized.

## Safety boundary

A passing report only means that startup-trust evidence is structurally ready for target-host validation.

The report always keeps:

```text
live_execution_allowed=false
sender_allowed=false
signer_allowed=false
```

This checkpoint does not create live capability, signer access, transaction submission, provider access, deployment mutation or secret loading.

## Focused verification

```bash
PYTHONPATH=. python -m py_compile \
  src/mpr20_typed_config_credential_sandbox_gate.py \
  tests/test_mpr20_typed_config_credential_sandbox_gate.py

PYTHONPATH=. python -m pytest -q \
  tests/test_mpr20_typed_config_credential_sandbox_gate.py
```

Expected result:

```text
17 passed
```

## Remaining materialization work

Full MPR-20 completion still requires follow-up cutover commits that replace active runtime behavior instead of only adding this contract:

1. generated typed config schema and signed policy bundle;
2. strict startup parser wired into every installed CLI/container/signer entrypoint;
3. runtime/signer secret split with authenticated IPC and no runtime key resolution;
4. content-bound secret generation, revocation, lease and max-use CAS store;
5. implemented Docker secret file contract and removed obsolete env variables;
6. registry-bound cluster/program/commitment authority;
7. startup doctor routed through the canonical hardened transport;
8. target-host AppArmor/seccomp/UID/volume/egress attestations;
9. bounded diagnostics/crash-log redaction corpus;
10. deletion or hard-disable of permissive config/secret/sandbox legacy paths.
