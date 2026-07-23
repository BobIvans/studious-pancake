# PR-198 sender-free installed-artifact gate

This slice continues **PR-198 — One Durable Sender-Free Runtime and Real Shadow
Evidence** with a narrow installed-artifact acceptance gate.

The pass-3 roadmap requires the PR-198 vertical to prove a real installed
sender-free runtime, durable terminal evidence and physical absence of sender
modules from the wheel/import graph. This slice covers the last part: an already
materialized wheel/container manifest must prove that live, signer and sender
surfaces are neither installed nor reachable from the runtime entrypoints.

## Scope

- validate required installed console entrypoints;
- validate wheel/image digest identities;
- validate installed module and reachable-module manifests;
- fail closed if `src.execution.senders`, signer or live submit modules appear;
- fail closed if a reachable module imports a forbidden sender/signer surface;
- fail closed if live/signer/sender capabilities are enabled;
- emit deterministic `pr198.sender-free-artifact-gate.v1` evidence.

## Non-goals

This PR does not enable:

- live trading;
- private-key loading;
- signer IPC;
- RPC/Jito submission;
- provider network calls;
- transaction construction or simulation;
- production database migrations.

It only defines a reviewable gate that future installed-artifact evidence must
satisfy before PR-199 can rely on PR-198 as a sender-free qualification boundary.

## Verification

```bash
python -m pytest -q tests/test_pr198_sender_free_artifact_gate.py
python -m compileall -q src/pr198_sender_free_artifact_gate.py tests/test_pr198_sender_free_artifact_gate.py
```

A passing report still sets:

```text
live_execution_allowed=false
signer_allowed=false
sender_import_allowed=false
```
