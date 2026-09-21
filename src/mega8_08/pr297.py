"""PR-297 / NF-873..876: explainable incident alerts."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega808Error, Result, require_nonnegative, result, stable_hash


def compose_explainable_alert(*, incident_type: str, evidence_ids: Sequence[str], summary: str) -> Result:
    ids=tuple(dict.fromkeys(str(x) for x in evidence_ids if str(x)))
    if not incident_type or not ids or not summary:
        raise Mega808Error("ALERT_EVIDENCE_REQUIRED")
    incident_id=stable_hash("incident",(incident_type,ids))
    return result("compose_explainable_alert", {"incident_id":incident_id,"incident_type":incident_type,"evidence_ids":ids,"summary":summary})


def route_alert_severity(*, incident_type: str, severity_policy: Mapping[str,str], owner_policy: Mapping[str,str]) -> Result:
    severity=severity_policy.get(incident_type)
    owner=owner_policy.get(incident_type)
    if severity not in {"INFO","WARN","HIGH","CRITICAL"} or not owner:
        raise Mega808Error("ALERT_ROUTE_UNMAPPED")
    return result("route_alert_severity", {"incident_type":incident_type,"severity":severity,"owner":owner})


def deduplicate_incident_alerts(alerts: Sequence[Mapping[str,object]]) -> Result:
    unique={}
    for alert in alerts:
        incident=str(alert.get("incident_id",""))
        if not incident:
            raise Mega808Error("INCIDENT_ID_REQUIRED")
        unique.setdefault(incident,dict(alert))
    return result("deduplicate_incident_alerts", {"alerts":tuple(unique[k] for k in sorted(unique)),"input_count":len(alerts),"unique_count":len(unique)})


def acknowledge_and_reconcile_alert(*, incident_id: str, acknowledged_by: str, resolution_evidence: str|None, resolved: bool) -> Result:
    if not incident_id or not acknowledged_by:
        raise Mega808Error("ALERT_ACK_REQUIRED")
    if resolved and not resolution_evidence:
        raise Mega808Error("RESOLUTION_EVIDENCE_REQUIRED")
    return result("acknowledge_and_reconcile_alert", {"incident_id":incident_id,"acknowledged_by":acknowledged_by,"resolved":resolved,"resolution_evidence":resolution_evidence})
