# PR-164 — Production alerting, on-call and incident-response delivery

This PR starts the roadmap PR-164 work as a review-safe, side-effect-free gate.
It does **not** send notifications, connect to PagerDuty/Slack/email, enable live
trading, sign transactions or submit anything on-chain.

## Problem

The production-readiness continuation audit identified that the repository can
surface internal booleans such as `operator_alert=True`, but that is not the same
as routed, delivered, acknowledged and escalated production alerting.

For production-style soak and any later live canary, the system needs durable
evidence for:

- Prometheus-compatible alert rules;
- Alertmanager grouping, deduplication, inhibition, silences and resolved
  notifications;
- redundant P0/P1 delivery channels;
- restart-safe delivery, acknowledgement and escalation state;
- on-call ownership and deadlines;
- synthetic end-to-end alert tests;
- privacy-safe payloads;
- incident lifecycle, postmortem and evidence linkage;
- SLO/error-budget latches.

## What this slice adds

`src/incident_response_pr164.py` defines a pure evaluator for a reviewed alerting
evidence package:

- `AlertReceiver`
- `AlertRule`
- `AlertRoutePolicy`
- `DurableAlertStore`
- `OnCallPolicy`
- `SyntheticAlertDrill`
- `IncidentLifecyclePolicy`
- `ErrorBudgetPolicy`
- `evaluate_pr164_alerting(...)`

The evaluator fails closed when:

- no production-verified receiver exists;
- a P0/P1 alert does not route to at least two independent verified receivers;
- receiver acknowledgement is unsupported;
- grouping/dedup/inhibition/silence review/resolved notifications are missing;
- delivery state is not restart-safe;
- synthetic fire/receive/deliver/ack/escalate/resolve tests are incomplete;
- incident records cannot link alerts, latches, operator actions, recovery
  commands and evidence;
- alert payload examples contain secret-looking material;
- required rules such as runtime-not-ready, wallet-reserve-breach,
  ambiguous-submission, backup-failure and security-gate-failure are absent.

## Safety boundary

This is an offline contract only.

- No network calls.
- No notifier secrets.
- No live trading.
- No signer, sender or wallet code.
- No mutation of runtime, workflows or dependency files.
- A canary request remains blocked while alerting blockers exist.

## Follow-up implementation

Later PR-164 integration can feed this contract from real Prometheus rule files,
Alertmanager configuration, on-call schedules, incident storage and synthetic
delivery artifacts. That follow-up should happen before production-style soak and
must be mandatory before live canary review.
