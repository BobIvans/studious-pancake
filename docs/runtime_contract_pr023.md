# PR-023 runtime and product contract

## Supported surface

The only supported runtime entrypoint is `python arb_bot.py`.

Supported inspection commands:

```bash
python arb_bot.py status [--json]
python arb_bot.py capabilities [--json]
```

`python arb_bot.py` defaults to `run --mode shadow`. Until a strategy is both
configured in a non-disabled mode and declared `shadow-ready` or `live-ready`,
the process exits with code `3` and `NO_EXECUTABLE_STRATEGIES`.

## Exit codes

| Code | Meaning |
|---:|---|
| 0 | Inspection command succeeded or disabled mode was requested |
| 2 | Invalid/inconsistent configuration or capability contract |
| 3 | No strategy is executable under the declared capability matrix |
| 4 | Requested product mode is intentionally unavailable |

## Capability states

- `implemented`: code exists and satisfies the narrow role described by its
  matrix entry; this does not imply end-to-end execution readiness.
- `fixture-only`: useful tests/research code exists, but fixtures or protocol
  conformance are not production evidence.
- `shadow-ready`: permitted to run through the canonical exact-simulation and
  reconciliation pipeline without submission.
- `live-ready`: passed the required live promotion gates.
- `disabled`: intentionally unavailable.

The canonical registry is `config/capabilities.json`. Every registered strategy
must have exactly one matrix entry. Quarantined entries may allow only
`disabled` mode.

## Product modes

`disabled` is inspection-only. `paper`, `shadow`, and `live` are product-level
modes, separate from strategy mode. PR-023 exposes these names but does not
claim that a paper/shadow/live execution kernel exists.

The old environment flags are not promotion controls for the supported
launcher. Typed configuration and explicit promotion belong to later PRs.

## Promotion rule

Changing a capability from `fixture-only`/`disabled` to `shadow-ready` or
`live-ready` requires a reviewed code change that updates:

1. implementation and tests;
2. `config/capabilities.json`;
3. relevant external-contract pins/fixtures;
4. README/runtime documentation;
5. acceptance evidence from the corresponding roadmap PR.
