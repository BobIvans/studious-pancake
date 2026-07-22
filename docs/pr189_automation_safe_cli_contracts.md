# PR-189 — automation-safe CLI/check contracts

## Canonical command surface

PR-189 adds one versioned result envelope and one enforcing command:

```text
flashloan-checks <domain> inspect
flashloan-checks <domain> check
```

Supported domains:

```text
paper-vertical
production-debt
provider-readiness
release-soak
qualification-verdict
```

The installed aliases are:

```text
flashloan-bot paper-vertical inspect|check
flashloan-bot readiness inspect|check
flashloan-bot release-soak inspect|check --manifest PATH
flashloan-contracts provider-readiness inspect|check
```

The old `flashloan-bot paper-vertical-preflight` alias is intentionally mapped to
the enforcing check. It can no longer return process success for a blocked
preflight.

## Machine-readable result

Every PR-189 command emits:

```json
{
  "schema_version": "pr189.command-result.v1",
  "command": "paper-vertical",
  "command_mode": "check",
  "verdict": "blocked",
  "ready": false,
  "check_passed": false,
  "exit_code": 3,
  "reason_codes": ["blocked_pr_a1_canonical_paper_vertical_unwired"],
  "details": {}
}
```

Inspection of a valid blocked state exits zero because the requested inspection
completed, but it remains explicit:

```text
command_mode=inspect
verdict=blocked
ready=false
check_passed=null
exit_code=0
```

An enforcing check of the same state exits `3`.

## Shared exit taxonomy

| Code | Meaning |
|---:|---|
| 0 | inspection completed or enforcing check passed |
| 2 | malformed input or internal command error |
| 3 | valid evidence, but blocked/not ready |
| 4 | evidence is stale |
| 5 | required dependency is unavailable |
| 6 | security invariant violation |

The payload exit code is constructed from the command mode and verdict. A
mismatched payload cannot be instantiated.

## Compatibility

`production_debt_audit.py` and `d2_release_soak_bundle.py` accept explicit
`inspect` and `check` modes. Their former `--require-ready` option remains a
temporary deprecated alias for `check`.

PR-186 already separates qualification planning from executed signed verdicts.
PR-189 consumes that signed verdict through:

```text
flashloan-checks qualification-verdict check \
  --verdict qualification-verdict.json \
  --attestation-key-file qualification-verifier.key
```

A plan or unsigned/invalid verdict cannot pass this check.

## Safety

This PR changes command and automation semantics only.

```text
live_enabled = false
signer_reachable = false
sender_reachable = false
submission_enabled = false
```

No provider request, transaction construction, signing or submission is added.
