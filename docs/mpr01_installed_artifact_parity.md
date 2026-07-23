# MPR-01 installed artifact parity gate

This checkpoint extends the existing canonical sender-free paper platform with a
reviewable installed/source command-surface evidence gate.

The roadmap for MPR-01 requires one active sender-free paper/shadow vertical and
an installed artifact check that runs:

- `flashloan-bot --help`
- `flashloan-bot status`
- `flashloan-bot capabilities`
- `flashloan-bot config doctor`
- `flashloan-bot run --mode paper`

The new `scripts/verify_installed_artifact.py` collector validates that surface
without enabling live trading, Jito sending, signer IPC, sender namespaces, or
private-key handling.

## Scope

Added:

- `src/canonical_paper/installed_artifact.py`
- `scripts/verify_installed_artifact.py`
- `tests/test_mpr01_installed_artifact_parity.py`

The evaluator requires:

1. the installed `flashloan-bot` entrypoint to resolve to `src.cli_pr189:main`;
2. the root wrapper target to remain the same canonical entrypoint;
3. the sender namespace to remain excluded from the sender-free wheel;
4. all MPR-01 command observations to be present exactly once;
5. expected argv and exit codes for the sender-free command surface;
6. captured JSON/text output not to promote live, Jito, signer, sender, or
   private-key claims;
7. deterministic evidence and command-surface digests.

## Usage

Source checkout verification:

```bash
python scripts/verify_installed_artifact.py --json
```

Installed console verification after building/installing the wheel:

```bash
python scripts/verify_installed_artifact.py \
  --installed-command flashloan-bot \
  --manifest-output .runtime/mpr01-installed-artifact-manifest.json \
  --json
```

A passing report still contains:

```text
live_enabled=false
signer_loaded=false
sender_loaded=false
```

## Non-goals

This PR does not build the final release wheel, publish an image, perform
provider/RPC calls, load wallet material, enable live, or claim production
paper/shadow readiness. It adds the fail-closed parity gate that later MPR-01
physical cutover work must satisfy before production-debt blockers are closed.
