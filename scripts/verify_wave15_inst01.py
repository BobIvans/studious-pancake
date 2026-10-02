#!/usr/bin/env python3
from dataclasses import asdict
import json
from src.research.wave15_institution import run_inst01_demo

def main()->int:
    r=run_inst01_demo(); v=r["verdict"]
    out={"roadmap":"WAVE15_INST01","status":v.status,"synthetic_only":v.synthetic_only,
         "production_ready":v.production_ready,"live_authorized":v.live_authorized,
         "winner":r["decision"].winner_id,"payment":r["decision"].payment,
         "verification":r["receipt"].status,"episode":r["episode"].terminal_status,
         "trace_hash":r["trace_hash"],"verdict":asdict(v)}
    print(json.dumps(out,sort_keys=True,separators=(",",":")))
    return 0 if v.status=="PASS_FINITE_SYNTHETIC" else 1
if __name__=="__main__": raise SystemExit(main())
