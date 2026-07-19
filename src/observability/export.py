from __future__ import annotations
import hashlib, json, os, time
from pathlib import Path
from .store import ObservabilityStore
from .redaction import REDACTION_VERSION
EXPORT_TOOL_VERSION="observability-export.v1"
def export_jsonl(store: ObservabilityStore, out_dir: str|Path) -> dict:
    rows=list(store.db.execute("SELECT * FROM event_log ORDER BY occurred_at_utc_ns,event_id")); out=Path(out_dir); out.mkdir(parents=True,exist_ok=True)
    if not rows: return {"event_count":0}
    date="1970-01-01"; et=rows[0]["event_type"]; part=out/f"date_utc={date}"/f"event_type={et}"; part.mkdir(parents=True,exist_ok=True)
    tmp=part/"events.jsonl.tmp"; final=part/"events.jsonl"
    with open(tmp,"w",encoding="utf-8") as f:
        for r in rows: f.write(r["payload_json"]+"\n")
        f.flush(); os.fsync(f.fileno())
    data=tmp.read_bytes(); checksum=hashlib.sha256(data).hexdigest(); os.replace(tmp, final)
    manifest_id=hashlib.sha256((str(final)+checksum).encode()).hexdigest()
    with store.db:
        store.db.execute("INSERT OR IGNORE INTO export_manifest(manifest_id,partition_path,checksum,event_count,first_event_id,last_event_id,schema_version,redaction_version,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (manifest_id,str(final),checksum,len(rows),rows[0]["event_id"],rows[-1]["event_id"],rows[0]["schema_version"],REDACTION_VERSION,time.time()))
        store.db.execute("UPDATE outbox SET status='done', completed_at=? WHERE status='pending'", (time.time(),))
    return {"manifest_id":manifest_id,"checksum":checksum,"event_count":len(rows),"path":str(final),"export_tool_version":EXPORT_TOOL_VERSION}
