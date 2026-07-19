from __future__ import annotations
import argparse, hashlib, json, sys
from .store import ObservabilityStore

def build_parser():
    p=argparse.ArgumentParser(description="Offline deterministic PR-017 event replay (network-free by default)")
    p.add_argument("--db", required=False, help="SQLite observability database")
    g=p.add_mutually_exclusive_group(); g.add_argument("--event-id"); g.add_argument("--opportunity-id"); g.add_argument("--attempt-id")
    p.add_argument("--format", choices=["json","text"], default="text"); p.add_argument("--verify", action="store_true"); p.add_argument("--what-if", help="named non-authoritative parameter set")
    return p

def main(argv=None):
    args=build_parser().parse_args(argv)
    if not args.db: return 0
    store=ObservabilityStore(args.db)
    if args.event_id:
        row=store.db.execute("SELECT * FROM event_log WHERE event_id=?",(args.event_id,)).fetchone(); rows=[row] if row else []
    elif args.attempt_id: rows=store.events_for(attempt_id=args.attempt_id)
    elif args.opportunity_id: rows=store.events_for(opportunity_id=args.opportunity_id)
    else:
        print("selector required", file=sys.stderr); return 2
    if not rows: print("no matching event stream", file=sys.stderr); return 3
    prev=-1; div=[]; timeline=[]
    for r in rows:
        if r["sequence_no"] <= prev: div.append({"code":"ORDERING_DIVERGENCE","event_id":r["event_id"]})
        prev=r["sequence_no"]
        payload=json.loads(r["payload_json"]); d=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
        if args.verify and d != r["payload_digest"]: div.append({"code":"PAYLOAD_DIGEST_DIVERGENCE","event_id":r["event_id"]})
        timeline.append({"event_id":r["event_id"],"sequence_no":r["sequence_no"],"event_type":r["event_type"],"reason_code":r["reason_code"],"outcome":r["outcome"],"payload_digest":r["payload_digest"]})
    out={"network_free":True,"timeline":timeline,"divergences":div,"what_if":args.what_if or None}
    if args.format=="json": print(json.dumps(out,sort_keys=True))
    else:
        print("# Offline replay\n")
        for e in timeline: print(f"{e['sequence_no']}: {e['event_type']} outcome={e['outcome']} reason={e['reason_code']} digest={e['payload_digest']}")
        if div: print("DIVERGENCES: "+json.dumps(div))
    return 4 if div else 0
if __name__ == "__main__": raise SystemExit(main())
