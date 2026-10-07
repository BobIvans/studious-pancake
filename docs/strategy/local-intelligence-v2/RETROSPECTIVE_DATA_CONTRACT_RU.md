# Retrospective Data Contract

## Should Studious gather more data?

Yes — but mostly more structured lineage and negative examples, not more undifferentiated raw blobs.

The highest-value retrospective data is:
what the system knew at that time, what decision it made, why it rejected/accepted, and what happened later.

## Required fields per source observation

Reuse AGG-02 / MarketObservationV2 fields and preserve:

Identity:
- event_id / observation_id
- source_id
- provider generation
- decoder/schema version
- instrument/pair/pool/market identity
- route/binding identity where known

Time:
- source_event_time
- received_at
- available_at
- source slot/block/checkpoint
- uncertainty
- reconnect epoch

Transport:
- request fingerprint
- HTTP/provider status class
- retry count
- latency
- rate-limit/quota state
- response hash
- raw payload hash

Quality:
- freshness
- completeness
- gap_before
- correction/retraction
- decoder warning
- provider disagreement class

## Required fields per normalized quote/edge

- exact amount in
- exact guaranteed amount out
- fee components
- price impact
- route legs
- program/market/pool IDs
- source observation refs
- age / slot skew
- liquidity/depth features if actually known
- normalization version

Do not invent unavailable values.

## Required fields per strategy decision

This is essential for retrospective AI.

- experiment_id
- repo_sha
- config_sha
- strategy_id + strategy version
- policy hash
- candidate_id
- decision stage
- inputs available at the stage
- selected action / rejection
- stable reason code
- thresholds used
- cheap pre-quote features
- upstream observation refs
- decision timestamp
- model/Laya decision refs if used

Every rejection should become analyzable data, not disappear.

## Preserve negative examples

Do not train/analyze only winners.

Keep bounded negative examples:
- no-candidate quiet windows;
- detector rejects;
- stale quotes;
- capacity rejects;
- simulation failures;
- reconciliation failures;
- provider disagreement without candidate;
- candidate that looked good but collapsed after exact verification.

Negative sampling policy:
- keep all rare failure classes;
- keep first/last of repeated class;
- reservoir sample common failures;
- keep periodic no-signal market snapshots;
- pin any negative used by an experiment/report.

## Candidate episode

Build one immutable episode binding:

- experiment/repo/config identity
- pre-candidate observation window
- candidate
- all provider/source refs
- quote/refinement
- sizing
- planner
- compiler
- simulation
- reconciliation
- paper outcome
- rejection/terminal reason
- resource use
- data quality/gaps
- Laya research-value decisions

This should reuse market_data_evolution.MarketEpisode rather than inventing a competing concept.

## Counterfactual-friendly metadata

For future analysis, record:
- candidate rank among alternatives
- alternatives considered
- reason higher-ranked route won
- rejected route reason
- available provider set at decision time
- quota/circuit state
- latency budget remaining
- observation age at each stage
- exact threshold versions

This allows questions such as:
Would another route have survived if latency were lower?
Did a provider add unique useful candidates?
Did a threshold reject future-positive episodes?
Which failures are caused by stale data vs strategy logic?

## Avoid lookahead leakage

Features used for retrospective model scoring must carry:
- available_at
- stage
- source refs

A future terminal outcome may be a label, not a feature for a past PRE_QUOTE decision.

Reuse src/decision/dataset.py semantics.

## Raw logs and simulation logs

Do not store all verbose logs forever.

For ordinary successes:
- structured fields + log hash + bounded selected diagnostics.

For rare/failed/unknown episodes:
- retain full bounded logs if they are useful for diagnosis and contain no secrets.

## Strategy comparison

Reuse production_qualification helpers where possible:
- build_agg04_funnel
- compare_agg04_baselines
- summarize_agg04_delay_stress
- build_agg04_dashboard

Add only missing provider-utility / disk-cost / Laya-triage dimensions.
