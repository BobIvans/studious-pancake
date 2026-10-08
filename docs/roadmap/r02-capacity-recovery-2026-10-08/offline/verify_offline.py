#!/usr/bin/env python3
"""Offline R-02 source and ABI integrity check. stdlib only, NO NETWORK."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def read_json(file: str) -> dict:
    return json.loads((ROOT / file).read_text(encoding="utf-8"))

def git_blob_sha(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()

def validate() -> dict:
    manifest = read_json("VENDOR_MANIFEST.json")
    entries = manifest["entries"]
    assert len(entries) >= 19, "Missing expected offline source files"
    seen = set()
    for e in entries:
        rel = e["local_path"]
        assert rel.startswith("offline/vendor/"), "unexpected vendor path"
        path = ROOT.parent / rel
        assert path.is_file() and rel not in seen, "missing/duplicate vendor"
        seen.add(rel)
        raw = path.read_bytes()
        assert git_blob_sha(raw) == e["upstream_git_blob_sha"], "vendor content modified"
        assert len(raw) == e["bytes"], "vendor byte count mismatch"
        assert e["license_label"].startswith("MIT"), "unknown license; do not bundle"
        assert e["reference_only"] is True
    j = read_json("jupiter_token_reserve_layout.json")
    k = read_json("kamino_reserve_prefix_layout.json")
    n = read_json("navi_sdk_bridge_facts.json")
    zero = read_json("p0_public_discovery_facts.json")
    assert j["source_blob"] == "09209f553900df7da61f84a106ad85767fdac71d"
    assert j["account_size_bytes"] == 192
    assert j["discriminator"] == [21,18,59,135,120,20,31,12]
    assert k["prefix_len_bytes"] == 280
    assert k["reserve_discriminator"] == [43,242,204,202,26,247,59,127]
    assert k["fee_state_reference"]["scale"] == "2^60"
    assert n["version"] == "2.0.12"
    assert zero["source_git_version"] == "2.10.0"
    for rel in ["CODEX_START_HERE.md","MASTER_CONTEXT.md","R02_UNBLOCK_MATRIX.md","R03_SHADOW_BUILDERS.md","R02_ACCEPTANCE.md","P0_PUBLIC_ACCOUNT_PATH.md","LICENSE_AND_PROVENANCE.md"]:
        assert (ROOT.parent / rel).is_file(), "missing assignment doc " + rel
    return {"status":"OFFLINE_REFERENCE_INTEGRITY_PASS","vendor_files":len(entries),
            "jupiter_bytes":192,"kamino_prefix_bytes":280,"live_readers_qualified":0,
            "execution_authority":"NONE","network_requests":0}

if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
