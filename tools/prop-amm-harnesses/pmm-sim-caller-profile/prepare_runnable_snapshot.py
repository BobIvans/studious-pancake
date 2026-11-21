#!/usr/bin/env python
"""Prepare a runnable pmm-sim snapshot directory from a captured snapshot.

Inputs:
  - research/pmm-sim-caller-profile/snapshot/<slot>/   (capture_snapshot.py output)
  - vendor/strategy-research/pmm-sim-cc4ae891/cfg/     (pinned mirror: setup.toml, router/spoof binaries)

Output: research/pmm-sim-caller-profile/snapshot/<slot>/cfg/
  cfg/setup.toml         (copied from the pinned mirror)
  cfg/accounts/*.json    (captured accounts converted to pmm-sim's RPC-like JSON format)
  cfg/programs/*.so      (humidifi.so = CAPTURED deployed ELF; magnus-router.so + spoof binaries
                          copied from the pinned mirror — local LiteSVM-only harness binaries)
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import sys
from pathlib import Path


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot_dir")
    ap.add_argument("--mirror-cfg", required=True, help="vendor/strategy-research/pmm-sim-cc4ae891/cfg")
    args = ap.parse_args()

    snap = Path(args.snapshot_dir)
    mirror_cfg = Path(args.mirror_cfg)
    manifest = json.loads((snap / "SNAPSHOT_MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("owner_assertions") != "PASS":
        print("refusing: snapshot owner assertions did not pass", file=sys.stderr)
        return 1

    cfg = snap / "cfg"
    if cfg.exists():
        shutil.rmtree(cfg)
    (cfg / "accounts").mkdir(parents=True)
    (cfg / "programs").mkdir(parents=True)

    shutil.copy2(mirror_cfg / "setup.toml", cfg / "setup.toml")
    # Local LiteSVM-only harness binaries (router + spoofs) come from the pinned mirror.
    for so in mirror_cfg.glob("programs/*.so"):
        if so.name != "humidifi.so":
            shutil.copy2(so, cfg / "programs" / so.name)

    # Captured HumidiFi ELF from the loader-v3 program-data account (header: u32 + u64 slot + Option<Pubkey>).
    pd = json.loads((snap / "accounts" / f"{manifest['humidifi_program_data_address']}.json").read_text(encoding="utf-8"))
    raw = base64.b64decode(pd["data_base64"])
    off = 4 + 8 + 1 + 32
    elf = raw[off:]
    if elf[:4] != b"\x7fELF":
        print("refusing: extracted program ELF magic invalid", file=sys.stderr)
        return 1
    (cfg / "programs" / "humidifi.so").write_bytes(elf)

    converted = 0
    dex_prefixes = ["humidifi", "humidifi-swap-v2", "humidifi-swap-v3"]
    for acc_file in sorted((snap / "accounts").glob("*.json")):
        rec = json.loads(acc_file.read_text(encoding="utf-8"))
        # pmm-sim reads account files by dex prefix; skip executables/program-data
        # (loader accounts are not market state).
        if rec.get("executable") or rec["owner"] == "BPFLoaderUpgradeab1e11111111111111111111111":
            continue
        out = {
            "slot": manifest["slot"],
            "pubkey": rec["pubkey"],
            "account": {
                "data": [rec["data_base64"], "base64"],
                "executable": rec["executable"],
                "lamports": rec["lamports"],
                "owner": rec["owner"],
                "rentEpoch": rec.get("rent_epoch", 0),
            },
        }
        for prefix in dex_prefixes:
            (cfg / "accounts" / f"{prefix}_{rec['pubkey']}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
        converted += 1

    programs_manifest = {
        "schema": "studious-pancake.pmm-sim-runnable-snapshot.v1",
        "source_snapshot_slot": manifest["slot"],
        "whole_snapshot_digest": manifest["whole_snapshot_digest"],
        "humidifi_program_elf_sha256_captured": sha256(cfg / "programs" / "humidifi.so"),
        "programs_sha256": {p.name: sha256(p) for p in sorted((cfg / "programs").glob("*.so"))},
        "accounts_converted": converted,
        "note": "humidifi.so is CAPTURED deployed bytes (GENUINE provenance); magnus-router*.so are harness-shipped (SYNTHETIC provenance, local LiteSVM only)",
    }
    (cfg / "RUNNABLE_SNAPSHOT_MANIFEST.json").write_text(json.dumps(programs_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"OK converted={converted} humidifi_elf_sha256={programs_manifest['humidifi_program_elf_sha256_captured']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
