# MPR-05 — Continuous installed paper/shadow qualification and 72-hour soak

This branch starts the V4 roadmap package **MPR-05**.

It is intentionally additive and sender-free. It does not start a provider, signer,
sender, RPC client, transaction builder, simulator or live runtime. It adds a typed
acceptance gate for the evidence that a future installed release artifact must
produce after MPR-01 through MPR-04 are accepted.

## V4 roadmap scope

MPR-05 absorbs the previous PR-200 and qualification portions of PR-201. It is not
allowed to be a parallel runner. The required evidence must come from the exact
installed sender-free production composition produced by MPR-01 through MPR-04.

The gate added here models:

- installed wheel and container execution;
- exact MPR-01, MPR-02, MPR-03 and MPR-04 generation hashes;
- a 72-hour sender-free paper/shadow soak;
- deterministic capture and replay;
- provider outage, database contention, cancellation, restart, clock/slot drift,
  backlog pressure and forced restart fault injections;
- zero unexplained balance loss, evidence loss, leaked reservations and leaked
  outbox claims;
- workload readiness that fails even when the management listener is alive if a
  mandatory worker is dead or stale;
- a signed, immutable and offline-re-verifiable soak artifact;
- hard absence of live execution, signer and sender reachability.

## Files

- `src/mpr05_installed_paper_shadow_qualification.py`
- `tests/test_mpr05_installed_paper_shadow_qualification.py`
- `.github/workflows/mpr05-installed-paper-shadow-qualification.yml`

## What this branch proves

The branch gives future release qualification a single deterministic contract:

```text
mpr05.installed-paper-shadow-qualification.v1
```

A complete fixture can evaluate to `ready_sender_free`, but only when every
requirement is explicitly present. The report blocks on:

- short soak duration;
- use of a parallel runner instead of the installed production composition;
- missing accepted MPR-01…MPR-04 dependencies;
- any admitted candidate without a durable terminal state within SLO;
- balance/evidence loss or leaked reservations/outbox claims;
- replay mismatches or insufficient replay cases;
- missing fault injection scenarios;
- unsigned, mutable or non-re-verifiable artifacts;
- any reachable live/signer/sender surface.

## What this branch does not prove yet

This is not the real 72-hour soak implementation. It does not claim paper-ready
or shadow-qualified status. A later MPR-05 implementation must connect this gate
to the actual installed wheel/container produced by MPR-01…04 and feed it real,
signed, immutable evidence.

## Suggested verification

```bash
python -m py_compile \
  src/mpr05_installed_paper_shadow_qualification.py \
  tests/test_mpr05_installed_paper_shadow_qualification.py
python -m pytest -q tests/test_mpr05_installed_paper_shadow_qualification.py
```

## Safety invariant

A passing MPR-05 report is still sender-free:

```text
live_execution_allowed = false
signer_or_sender_reachable = false
```
