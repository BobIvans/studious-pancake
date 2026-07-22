# PR-192 — runtime memory confidentiality and crash-artifact hardening

PR-192 adds an active, fail-closed boundary for the period after a credential or
signed payload has been materialized inside a process. It does not enable live
trading, a signer, transaction submission, or credential fetching in CI.

## Runtime entrypoint

The installed `flashloan-bot` command enters through `src.secure_cli`. The wrapper
applies and verifies memory controls before importing `src.cli`, so configuration,
credential resolution, provider construction, and runtime composition are not
reached when required hardening fails.

Production/container mode requires Linux and proves:

- `RLIMIT_CORE` soft and hard limits are both zero;
- Linux `PR_SET_DUMPABLE=0` is applied and verified with `PR_GET_DUMPABLE`;
- `/proc/self/status` reports `TracerPid: 0`;
- failures contain stable reason codes rather than operating-system exception text.

## Deployment enforcement

The reviewed Compose profile sets a zero core ulimit and requires memory
hardening. Its default-deny seccomp profile allows only the `prctl` and resource
limit syscalls needed by the launcher and does not allow `ptrace`,
`process_vm_readv`, `process_vm_writev`, `kcmp`, or `perf_event_open`.

`validate_memory_confidentiality.py` fails closed if the policy, Compose profile,
seccomp profile, or installed entrypoint loses one of these controls.

## Secrets in process memory

`SecretHandle` retains the existing redacted representation and bytearray-backed
storage. Runtime consumers can now use a scoped, read-only `memoryview` through
`borrow_bytes()` or `use_bytes()` and can revoke/zero the backing buffer
immediately after use. `reveal()` remains only as a compatibility API and creates
an immutable Python string; new credentialed runtime code should avoid it.

This is best-effort hardening, not a claim that CPython can provide guaranteed
zeroization of every allocator or native-library copy. Prefer KMS/HSM or remote
signing/authentication APIs that avoid returning raw key material to Python.

## Crash and support artifacts

Crash artifacts are metadata-only. They include an exception type and stable
reason code but never exception text, arguments, tracebacks, locals, environment,
headers, provider bodies, config trees, transaction bytes, signatures, or wallet
topology. Support bundles reject every field outside a fixed allowlist.

## Host and signer requirements

Production qualification must additionally prove outside the container:

- swap is disabled or encrypted;
- storage and hibernation images are encrypted;
- host coredump collection is disabled or tightly restricted and retained under
  an approved incident policy;
- unmanaged profilers/debuggers and broad host administrator access are denied;
- support-bundle upload is authenticated and access-controlled.

A future signer service must use a stricter, separate sandbox: no general network,
no shell/debug tooling, no shared PID namespace, no core dump, minimal syscall
surface, and preferably a distinct process/host or hardware-backed signer.

## Verification

Focused tests cover successful and failed hardening, active-tracer rejection,
redaction of secret-bearing OS errors, a real disposable Linux subprocess,
crash/support allowlists, secure entrypoint ordering, seccomp inspection denial,
and scoped secret-buffer zeroization.
