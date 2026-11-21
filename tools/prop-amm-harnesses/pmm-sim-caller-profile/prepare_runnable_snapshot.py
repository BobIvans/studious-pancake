#!/usr/bin/env python
"""Prepare a runnable pmm-sim snapshot directory from a captured snapshot or the pinned mirror.

Two sources:
  --source capture  : research/pmm-sim-caller-profile/snapshot/<slot>/  (capture_snapshot.py output)
  --source mirror   : vendor/strategy-research/pmm-sim-cc4ae891 (pinned upstream mirror, pristine)

Output (always a NEW runtime directory, mirrors stay untouched):
  <out>/cfg/setup.toml          (pinned mirror setup.toml)
  <out>/cfg/accounts/*.json     (pmm-sim RPC-like JSON, dex-prefixed)
  <out>/cfg/programs/humidifi.so
  <out>/cfg/programs/humidifi-swap-v2.so / -v3.so  — CANDIDATE ALIASES (byte-identical copies;
      lifecycle: candidate -> verified only after Gate A executes all three version-specific
      instruction layouts. Redistribution-license status is tracked separately in the N01
      dossier and is NEVER inferred from on-chain availability or upstream mirroring.)
  <out>/cfg/programs/magnus-router*.so  (harness-shipped local-LiteSVM-only binaries)
  <out>/cfg/RUNNABLE_SNAPSHOT_MANIFEST.json

Aliased files are recorded with alias_of + sha256 equality proof; they are NOT independent binaries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

MIRROR_DEFAULT = "vendor/strategy-research/pmm-sim-cc4ae891"
BPF_LOADER = "BPFLoaderUpgradeab1e11111111111111111111111"
ALIASES = ["humidifi-swap-v2.so", "humidifi-swap-v3.so"]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["capture", "mirror"], required=True)
    ap.add_argument("source_path", help="snapshot dir (capture) or repo root (mirror)")
    ap.add_argument("--out", required=True, help="runtime snapshot dir to create")
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "cfg" / "accounts").mkdir(parents=True)
    (out / "cfg" / "programs").mkdir(parents=True)

    manifest: dict = {
        "schema": "studious-pancake.pmm-sim-runnable-snapshot.v2",
        "source_kind": args.source,
        "alias_policy": "humidifi-swap-v2.so / humidifi-swap-v3.so are byte-identical ALIASES of humidifi.so "
        "(same deployed program id 9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp); lifecycle candidate->verified "
        "only after Gate A executes all three version-specific instruction layouts",
        "alias_status": "candidate",
        "activation_flags": {
            "capture": False,
            "paid_feed": False,
            "provider_activation": False,
            "simulation_live_network": False,
            "sign": False,
            "send": False,
            "borrow": False,
            "live": False,
        },
    }

    if args.source == "mirror":
        root = Path(args.source_path)
        mirror_cfg = root / MIRROR_DEFAULT / "cfg"
        if not (mirror_cfg / "setup.toml").exists():
            print(f"refusing: mirror cfg not found at {mirror_cfg}", file=sys.stderr)
            return 1
        shutil.copy2(mirror_cfg / "setup.toml", out / "cfg" / "setup.toml")
        for so in (mirror_cfg / "programs").glob("*.so"):
            shutil.copy2(so, out / "cfg" / "programs" / so.name)
        # accounts: mirror ships dex-prefixed files already; copy as-is
        for acc in (mirror_cfg / "accounts").glob("*.json"):
            shutil.copy2(acc, out / "cfg" / "accounts" / acc.name)
        primary = out / "cfg" / "programs" / "humidifi.so"
        manifest.update(
            {
                "source_snapshot_slot": 401101387,
                "snapshot_status": "UPSTREAM_MIRROR_CAPTURE_ONLY",
                "humidifi_program_elf_sha256": sha256(primary),
                "accounts_source": f"{MIRROR_DEFAULT}/cfg/accounts (upstream-shipped)",
                "programs_source": f"{MIRROR_DEFAULT}/cfg/programs (upstream-shipped, harness-only in LiteSVM)",
            }
        )
        accounts_converted = sum(1 for _ in (out / "cfg" / "accounts").glob("*.json"))
    else:
        snap = Path(args.source_path)
        snap_manifest = json.loads(
            (snap / "SNAPSHOT_MANIFEST.json").read_text(encoding="utf-8")
        )
        if snap_manifest.get("owner_assertions") != "PASS":
            print("refusing: snapshot owner assertions did not pass", file=sys.stderr)
            return 1
        shutil.copy2(snap / "cfg" / "setup.toml", out / "cfg" / "setup.toml")
        for so in (snap / "cfg" / "programs").glob("*.so"):
            if so.name != "humidifi.so":
                shutil.copy2(so, out / "cfg" / "programs" / so.name)
        primary = snap / "cfg" / "programs" / "humidifi.so"
        shutil.copy2(primary, out / "cfg" / "programs" / "humidifi.so")

        dex_prefixes = ["humidifi", "humidifi-swap-v2", "humidifi-swap-v3"]
        accounts_converted = 0
        for acc_file in sorted((snap / "cfg" / "accounts").glob("*.json")):
            rec = json.loads(acc_file.read_text(encoding="utf-8"))
            if rec["account"]["executable"] or rec["account"]["owner"] == BPF_LOADER:
                continue
            inner = {
                "slot": snap_manifest["slot"],
                "pubkey": rec["pubkey"],
                "account": {
                    "data": [rec["account"]["data"][0], "base64"],
                    "executable": rec["account"]["executable"],
                    "lamports": rec["account"]["lamports"],
                    "owner": rec["account"]["owner"],
                    "rentEpoch": rec["account"].get(
                        "rentEpoch", rec["account"].get("rent_epoch", 0)
                    ),
                },
            }
            for prefix in dex_prefixes:
                (
                    out / "cfg" / "accounts" / f"{prefix}_{rec['pubkey']}.json"
                ).write_text(json.dumps(inner, indent=1) + "\n", encoding="utf-8")
            accounts_converted += 1
        manifest.update(
            {
                "source_snapshot_slot": snap_manifest["slot"],
                "whole_snapshot_digest": snap_manifest["whole_snapshot_digest"],
                "humidifi_program_elf_sha256": sha256(primary),
                "accounts_converted": accounts_converted,
                "snapshot_status": "RAW_ACCOUNT_CAPTURE_ONLY",
            }
        )

    # candidate aliases: byte-identical copies, recorded explicitly
    alias_entries = {}
    for alias in ALIASES:
        target = out / "cfg" / "programs" / alias
        shutil.copy2(primary, target)
        alias_entries[alias] = {
            "alias_of": "humidifi.so",
            "sha256": sha256(target),
            "equals_primary": sha256(target) == sha256(primary),
            "status": "candidate",
        }
    manifest["aliases"] = alias_entries
    manifest["alias_sha256_equality_proof"] = all(
        a["equals_primary"] for a in alias_entries.values()
    )

    (out / "cfg" / "RUNNABLE_SNAPSHOT_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"OK source={args.source} accounts={accounts_converted} "
        f"humidifi_elf_sha256={manifest['humidifi_program_elf_sha256']} "
        f"aliases={list(alias_entries)} alias_status=candidate"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
