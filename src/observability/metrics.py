from __future__ import annotations
import json
from collections import Counter, defaultdict
from statistics import median
from .store import ObservabilityStore

def _p95(vals):
    if len(vals) < 2: return "N/A"
    vals=sorted(vals); idx=int(0.95*(len(vals)-1)); return vals[idx]
def _p50(vals): return "N/A" if len(vals)<2 else median(vals)

def rejection_funnel(store: ObservabilityStore) -> dict:
    counts=Counter(); reasons=Counter(); lat=defaultdict(list)
    for r in store.db.execute("SELECT event_type,reason_code,payload_json FROM event_log"):
        counts[r["event_type"]]+=1
        if r["reason_code"]: reasons[r["reason_code"]]+=1
        attrs=json.loads(r["payload_json"]).get("attributes",{})
        if "latency_ms" in attrs and isinstance(attrs["latency_ms"], int): lat[r["event_type"]].append(attrs["latency_ms"])
    return {"stages":dict(counts),"reasons":dict(reasons),"latency":{"p50_ms":{k:_p50(v) for k,v in lat.items()},"p95_ms":{k:_p95(v) for k,v in lat.items()}},"ambiguous":reasons.get("AMBIGUOUS_SUBMISSION",0),"not_attempted":counts.get("feasibility_rejected",0)+counts.get("quote_rejected",0)}

def daily_shadow_summary(store: ObservabilityStore) -> dict:
    f=rejection_funnel(store)
    return {"volume_events":sum(f["stages"].values()),"top_rejection_reasons":sorted(f["reasons"].items(), key=lambda x:(-x[1],x[0]))[:10],"funnel":f,"simulated_pnl_distribution":"N/A","provider_health":"N/A","quota":"N/A"}
