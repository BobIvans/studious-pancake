#!/usr/bin/env python
"""Resumable, observable batch runner for the pmm-sim caller-profile matrix.

Safety: LOCAL LiteSVM research only. No signing, no sending, no borrowing, no live
network. Offline enforcement: a local black-hole TCP listener is the ONLY configured
RPC endpoint; ZERO accepted connections => ZERO_CONFIGURED_RPC_ATTEMPTS (recorded);
any accepted connection => OFFLINE_VIOLATION (recorded, gate fails). This proves the
absence of connections to the CONFIGURED endpoint — it is not absolute OS-level network
isolation (documented limitation).

Semantics (per user clarifications):
- attempts vs terminal records: max 3 attempts (initial + 2 retries), retries ONLY for
  classified transient infrastructure failures (thread setup failure, save error,
  process crash); deterministic swap failures are terminal scenario outcomes;
  after budget exhaustion => terminal BLOCKED_INFRA.
- durable per-amount events (written + fsync'd by the patched harness) are the evidence
  of record; a Parquet write failure must not destroy them; an incomplete artifact
  lifecycle is never a completed scenario.
- exactly one terminal record per scenario_id at the end; identical duplicates are
  deduplicated at merge time; conflicting terminal records hard-fail validation.
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HARNESS_VERSION = "v2-2026-11-22"
MAX_ATTEMPTS = 3  # initial + 2 retries

PROFILES = {
    "DIRECT": ["--call-type=direct"],
    "MAGNUS_NATIVE": ["--call-type=cpi"],
    "JUPITER_SIM": ["--call-type=cpi", "--spoof=jupiter"],
    "DFLOW_SIM": ["--call-type=cpi", "--spoof=dflow"],
    "OKX_SIM": ["--call-type=cpi", "--spoof=okxlabs"],
    "TITAN_SIM": ["--call-type=cpi", "--spoof=titan"],
}
VARIANTS = {
    "humidifi": {"dec": 9, "pair_dst": "usdc", "alt_market_dst": "usdc"},
    "humidifi-swap-v2": {"dec": 9, "pair_dst": "usdc", "alt_market_dst": "usd1"},
    "humidifi-swap-v3": {"dec": 9, "pair_dst": "usdc", "alt_market_dst": "usd1"},
}
WSOL_MARKET = "FksffEqnBRixYGR791Qw2MgdU7zNCpHVFYBL4Fa4qVuH"
USD1_MARKET = "5dhYayH9qvzNyCPoh2hKN8TJqumoGsWdyZ9UfPLXBfD9"
MARKETS = ["FksffEqnBRixYGR791Qw2MgdU7zNCpHVFYBL4Fa4qVuH", "DB3sUCP2H4icbeKmK6yb6nUxU5ogbcRHtGuq7W2RoRwW",
           "6n9VhCwQ7EwK6NqFDjnHPzEk6wZdRBTfh43RFgHQWHuQ", "AvGeFw71N5sNfV97mZ1uNrHg4yfufRicCJUrS9j2ehTX",
           "5dhYayH9qvzNyCPoh2hKN8TJqumoGsWdyZ9UfPLXBfD9"]
AMOUNT_LADDER = [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2000, 4000, 8000, 16000, 32000, 64000]

TERMINAL_OK = {"OK_COMPLETE_ROUND_TRIP"}
TERMINAL_DETERMINISTIC_PREFIX = ("FORWARD_SWAP_FAILED", "REVERSE_SWAP_FAILED")


def scenario_id(snapshot_id: str, pmm: str, market: str, profile: str, direction: str, amount: int) -> str:
    return f"{snapshot_id}|{pmm}|{market}|{profile}|{direction}|{amount}"


def market_suffix(market: str) -> str:
    return market[:4] if market in MARKETS[:3] else market[:4]


def build_batches(snapshot_id: str, mode: str, subset_ids: set[str] | None, terminal_index: dict,
                  identity: dict) -> tuple[list[dict], int]:
    """Build batch list; returns (batches, skipped_scenarios)."""
    batches = []
    skipped = 0
    b_idx = 0
    for pmm, meta in VARIANTS.items():
        for market in MARKETS:
            dst = meta["pair_dst"] if market != USD1_MARKET else meta["alt_market_dst"]
            directions = [f"wsol2{dst}", f"{dst}2wsol"]
            for profile, flags in PROFILES.items():
                for direction in directions:
                    amounts = list(AMOUNT_LADDER)
                    ids = [scenario_id(snapshot_id, pmm, market, profile, direction, a) for a in amounts]
                    if subset_ids is not None:
                        keep = [a for a, sid in zip(amounts, ids) if sid in subset_ids]
                        if not keep:
                            continue
                        amounts = keep
                        ids = [sid for sid in ids if sid in subset_ids]
                    # resume: drop scenarios with a matching, valid terminal record
                    pending = []
                    for a, sid in zip(amounts, ids):
                        t = terminal_index.get(sid)
                        if t and t.get("input_identity") == identity and t["status"] in TERMINAL_OK or (
                            t and t.get("input_identity") == identity and str(t["status"]).startswith(TERMINAL_DETERMINISTIC_PREFIX)
                        ):
                            skipped += 1
                        else:
                            pending.append(a)
                    if not pending:
                        continue
                    b_idx += 1
                    batch = {
                        "batch_id": f"b{b_idx:04d}_{pmm}_{market[:6]}_{profile}_{direction}",
                        "pmm": pmm, "market": market, "profile": profile,
                        "flags": flags, "direction": direction,
                        "src": "wsol" if direction.startswith("wsol") else dst,
                        "dst": dst if direction.startswith("wsol") else "wsol",
                        "amounts": [a for a in amounts if a in pending],
                        "scenario_ids": {str(a): sid for a, sid in zip(amounts, ids) if a in pending},
                    }
                    batches.append(batch)
    return batches, skipped


class BlackHoleListener:
    """Local black-hole RPC endpoint: the ONLY configured RPC URL for every benchmark process."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.attempts = 0
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        self.sock.settimeout(0.5)
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
                self.attempts += 1
                conn.close()
            except socket.timeout:
                continue
            except OSError:
                break

    @property
    def status(self) -> str:
        return "ZERO_CONFIGURED_RPC_ATTEMPTS" if self.attempts == 0 else f"OFFLINE_VIOLATION count={self.attempts}"

    def close(self) -> None:
        self._stop.set()
        self.thread.join(timeout=2)
        self.sock.close()


def classify_attempt(stderr_text: str, events: list[dict], rc: int, listener_attempts_delta: int,
                     parquet_rows: dict[int, dict], amounts: list[int], dec: int) -> tuple[dict[int, dict], str, bool]:
    """Returns (per_amount_terminal, offline_status, retryable_infra)."""
    offline = "ZERO_CONFIGURED_RPC_ATTEMPTS" if listener_attempts_delta == 0 else "OFFLINE_VIOLATION"
    save_failed = "[SAVE_ERROR]" in stderr_text
    thread_setup_failed = "benchmark thread failed" in stderr_text
    terminal: dict[int, dict] = {}
    retryable = False

    for a in amounts:
        raw_amount = a * 10**dec
        evs = [e for e in events if int(e.get("amount_in_raw", -1)) == raw_amount]
        ev = evs[-1] if evs else None
        if offline != "ZERO_CONFIGURED_RPC_ATTEMPTS":
            terminal[a] = {"status": "OFFLINE_VIOLATION", "failure_category": "offline_contract", "error_code": offline}
            continue
        if ev is None:
            # no durable event: infra (setup/thread crash) or crash before loop
            if thread_setup_failed or rc != 0:
                terminal[a] = {"status": "ATTEMPT_INCOMPLETE", "failure_category": "infra_transient",
                               "error_code": f"rc={rc} thread_setup={thread_setup_failed}"}
                retryable = True
            else:
                terminal[a] = {"status": "ARTIFACT_INCOMPLETE", "failure_category": "infra_transient",
                               "error_code": "no event; no deterministic swap failure recorded"}
                retryable = True
            continue
        fwd, rev, err = ev.get("forward_status"), ev.get("reverse_status"), str(ev.get("error_code", ""))
        if fwd == "failed":
            terminal[a] = {"status": f"FORWARD_SWAP_FAILED:{_short_code(err)}", "failure_category": "deterministic_swap",
                           "error_code": err[:400]}
        elif rev == "failed":
            terminal[a] = {"status": f"REVERSE_SWAP_FAILED:{_short_code(err)}", "failure_category": "deterministic_swap",
                           "error_code": err[:400]}
        else:
            row = parquet_rows.get(a)
            if row is None:
                terminal[a] = {"status": "ARTIFACT_INCOMPLETE", "failure_category": "infra_transient",
                               "error_code": "swap ok but row missing from artifact"}
                retryable = True
            else:
                terminal[a] = {"status": "OK_COMPLETE_ROUND_TRIP", "failure_category": "",
                               "error_code": "",
                               "amount_out_raw": row.get("amount_out_raw"), "compute_units": row.get("compute_units"),
                               "artifact_path": row.get("artifact_path")}
    return terminal, offline, retryable


def _short_code(err: str) -> str:
    import re
    m = re.findall(r"Custom\((\d+)\)", err)
    if m:
        return f"0x{int(m[-1]):x}"
    if "SBF program panicked" in err:
        return "SBF_PANIC"
    return (err.split(":")[-1].strip()[:24] or "UNKNOWN")


def read_events(batch_dir: Path) -> list[dict]:
    out = []
    for f in batch_dir.glob("events_*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # incomplete trailing line after crash: quarantined by absence
    return out


def read_parquet_rows(parquet: Path, amounts: list[int], dec: int) -> dict[int, dict]:
    rows = {}
    try:
        import pyarrow.parquet as pq
        table = pq.read_table(parquet).to_pylist()
        for r in table:
            if str(r.get("forward_status", "ok")) == "ok":
                a = int(round(float(r["amount_in"]) * 10**dec))
                rows[a] = {"amount_out_raw": int(r["amount_out"] * 10**dec), "compute_units": int(r["compute_units"]),
                           "artifact_path": str(parquet)}
    except Exception as exc:  # noqa: BLE001
        print(f"WARN parquet read failed {parquet}: {exc}", file=sys.stderr)
    return rows


def run_batch_attempt(sim: str, batch: dict, batch_dir: Path, snap_root: str, listener_url: str,
                      cfg_setup: str, log) -> tuple[int, str]:
    amounts_csv = ",".join(str(a) for a in batch["amounts"])
    cmd = [
        sim, "benchmark",
        f"--pmms={batch['pmm']}_{batch['market'][:4]}",
        f"--amounts={amounts_csv}",
        f"--src-token={batch['src']}", f"--dst-token={batch['dst']}",
        *batch["flags"],
        "--jit-accounts=false", "--jit-programs=false",
        f"--http-url={listener_url}",
        f"--setup-path={cfg_setup}/setup.toml",
        f"--programs-path={cfg_setup}/programs",
        f"--accounts-path={cfg_setup}/accounts",
        f"--datasets-path={batch_dir}",
    ]
    started = time.gmtime()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    (batch_dir / "batch.log").write_text(proc.stderr[-2_000_000:], encoding="utf-8")
    log(f"rc={proc.returncode} dir={batch_dir.name}")
    return proc.returncode, proc.stderr[-2_000_000:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", required=True)
    ap.add_argument("--snapshot", required=True, help="runnable snapshot dir (contains cfg/)")
    ap.add_argument("--snapshot-id", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", choices=["isolated", "batched"], default="batched")
    ap.add_argument("--subset", default=None, help="validation_subset_v1.json path or 'all'")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--build-receipt-sha", default="")
    args = ap.parse_args()

    snap_root = Path(args.snapshot) / "cfg"
    runnable_manifest = json.loads((snap_root / "RUNNABLE_SNAPSHOT_MANIFEST.json").read_text(encoding="utf-8"))
    identity = {
        "snapshot_digest": str(runnable_manifest.get("whole_snapshot_digest", runnable_manifest.get("humidifi_program_elf_sha256"))),
        "program_elf_sha": runnable_manifest.get("humidifi_program_elf_sha256"),
        "build_receipt_sha": args.build_receipt_sha,
        "harness_version": HARNESS_VERSION,
    }

    subset_ids = None
    if args.subset and args.subset != "all":
        subset = json.loads(Path(args.subset).read_text(encoding="utf-8"))
        subset_ids = {s["scenario_id"] for s in subset["scenarios"]}

    # load existing terminal records for resume
    out_root = Path(args.out) / args.snapshot_id
    journal_dir = out_root / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    terminal_index: dict[str, dict] = {}
    for f in journal_dir.glob("journal_w*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # incomplete trailing record: quarantined, will be re-run
            if rec.get("type") == "terminal":
                terminal_index[rec["scenario_id"]] = rec

    batches, skipped = build_batches(args.snapshot_id, args.mode, subset_ids, terminal_index, identity)
    dec = VARIANTS["humidifi"]["dec"]  # src wsol ladder in wsol decimals for wsol2x direction
    print(f"batches={len(batches)} skipped_scenarios={skipped} mode={args.mode} workers={args.workers}")

    listener = BlackHoleListener()
    listener_url = f"http://127.0.0.1:{listener.port}"
    worker_lock = threading.Lock()
    worker_counters = {"n": 0}

    journal_lines: list[str] = []

    def run_one(batch: dict, worker_id: str) -> list[dict]:
        nonlocal journal_lines
        terminals = []
        dec_src = 9 if batch["src"] == "wsol" else 6
        for attempt in range(1, MAX_ATTEMPTS + 1):
            batch_dir = out_root / "batches" / batch["batch_id"] / f"attempt_{attempt}"
            batch_dir.mkdir(parents=True, exist_ok=True)
            (batch_dir / "meta.json").write_text(
                json.dumps({"batch_id": batch["batch_id"], "attempt": attempt, "worker_id": worker_id,
                            "input_identity": identity, "command": [args.sim, "benchmark", f"--amounts={','.join(map(str, batch['amounts']))}"]},
                           indent=2, sort_keys=True) + "\n", encoding="utf-8")
            before = listener.attempts
            started = time.time()
            try:
                rc, stderr_text = run_batch_attempt(args.sim, batch, batch_dir, str(args.snapshot), listener_url, str(snap_root), lambda m: None)
            except subprocess.TimeoutExpired:
                rc, stderr_text = 124, "TIMEOUT after 900s"
            duration_ms = int((time.time() - started) * 1000)
            listener_delta = listener.attempts - before

            events = read_events(batch_dir)
            parquets = sorted(batch_dir.glob("*.parquet"))
            parquet_rows = read_parquet_rows(parquets[-1], batch["amounts"], dec_src) if parquets else {}
            terminal, offline_status, retryable = classify_attempt(stderr_text, events, rc, listener_delta, parquet_rows, batch["amounts"], dec_src)

            for a in batch["amounts"]:
                t = terminal[a]
                rec = {
                    "type": "terminal", "scenario_id": batch["scenario_ids"][str(a)],
                    "batch_id": batch["batch_id"], "worker_id": worker_id, "attempt": attempt,
                    "amount": a, "status": t["status"], "failure_category": t["failure_category"],
                    "error_code": t.get("error_code", ""), "artifact_path": t.get("artifact_path", ""),
                    "input_identity": identity, "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
                    "duration_ms": duration_ms, "offline_status": offline_status,
                }
                terminals.append(rec)
            journal_lines.append(json.dumps({"type": "attempt", "batch_id": batch["batch_id"], "worker_id": worker_id,
                                             "attempt": attempt, "rc": rc, "duration_ms": duration_ms,
                                             "offline_status": offline_status,
                                             "amounts": batch["amounts"]}, sort_keys=True))
            # retry only transient infra; deterministic/offline outcomes are terminal now
            if not retryable:
                break
            if offline_status != "ZERO_CONFIGURED_RPC_ATTEMPTS":
                break
            if all(not t["status"].startswith(("ATTEMPT_INCOMPLETE", "ARTIFACT_INCOMPLETE")) for t in terminal.values()):
                break
        return terminals

    def worker(batch: dict) -> list[dict]:
        with worker_lock:
            worker_counters["n"] += 1
            wid = f"w{worker_counters['n']}"
        return run_one(batch, wid)

    started_all = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(worker, batches))
    wall_s = time.time() - started_all

    # write per-worker journal lines (single writer per file: this process merges attempt logs)
    for i, terminals in enumerate(results, 1):
        with (journal_dir / f"journal_w{i}.jsonl").open("a", encoding="utf-8") as f:
            for rec in terminals:
                f.write(json.dumps(rec, sort_keys=True) + "\n")
    with (journal_dir / "journal_attempts.jsonl").open("a", encoding="utf-8") as f:
        for line in journal_lines:
            f.write(line + "\n")

    status_counts: dict[str, int] = {}
    for terminals in results:
        for rec in terminals:
            status_counts[rec["status"].split(":")[0]] = status_counts.get(rec["status"].split(":")[0], 0) + 1
    summary = {
        "snapshot_id": args.snapshot_id, "mode": args.mode, "workers": args.workers,
        "wall_clock_s": round(wall_s, 1), "batches": len(batches),
        "throughput_scenarios_per_s": round(sum(len(t) for t in results) / wall_s, 2) if wall_s else 0,
        "terminal_status_counts": status_counts,
        "offline_status": listener.status,
        "skipped_scenarios": skipped,
    }
    listener.close()
    (out_root / f"run_summary_{args.mode}_w{args.workers}.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if listener.attempts == 0 else 4


if __name__ == "__main__":
    sys.exit(main())
