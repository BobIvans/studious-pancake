"""One bounded sender-free campaign through the installed paper owner."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit

from .common import atomic_bytes, canonical, digest, save_json, seal


def run_paper_campaign(
    destination: str | Path,
    *,
    timeout_seconds: int = 30,
    environment: dict[str, str] | None = None,
) -> dict:
    """Never inspect a private key/seed or invoke a signer/sender entrypoint.

    The installed paper runner owns observations and stage outcomes. This adapter
    records its result, never fills a missing outcome with synthetic success.
    """
    source = os.environ if environment is None else environment
    public_key = source.get("FLASHLOAN_WALLET_PUBLIC_KEY")
    rpc_url = source.get("SOLANA_RPC_HTTP")
    out = Path(destination)
    if not 1 <= timeout_seconds <= 120:
        raise ValueError("campaign timeout must be 1..120 seconds")
    if out.exists() and any(out.iterdir()):
        raise ValueError("campaign output must be new or empty")
    out.mkdir(parents=True, exist_ok=True)
    missing = [
        name
        for name, value in (
            ("FLASHLOAN_WALLET_PUBLIC_KEY", public_key),
            ("SOLANA_RPC_HTTP", rpc_url),
        )
        if not value
    ]
    if missing:
        receipt = seal(
            {
                "schema": "studious.paper-campaign.v2",
                "status": "BLOCKED",
                "reason": "MISSING_PUBLIC_CONFIGURATION",
                "missing": missing,
                "process_started": False,
                "live_authorized": False,
            }
        )
        save_json(out / "CAMPAIGN_RECEIPT.json", receipt)
        return receipt
    assert public_key is not None and rpc_url is not None
    from solders.pubkey import Pubkey

    Pubkey.from_string(public_key)
    endpoint = urlsplit(rpc_url)
    if (
        endpoint.scheme != "https"
        or not endpoint.hostname
        or endpoint.username
        or endpoint.password
    ):
        raise ValueError("HTTPS read-only RPC configuration required")
    child = {
        key: source[key]
        for key in (
            "PATH",
            "SYSTEMROOT",
            "XDG_CACHE_HOME",
            "XDG_CONFIG_HOME",
            "PIP_CACHE_DIR",
            "SSL_CERT_FILE",
        )
        if key in source
    }
    child.update(
        {
            "FLASHLOAN_WALLET_PUBLIC_KEY": public_key,
            "SOLANA_RPC_HTTP": rpc_url,
            "FLASHLOAN_RUNTIME_MODE": "paper",
            "FLASHLOAN_JITO_ENABLED": "false",
            "FLASHLOAN_MARGINFI_ENABLED": "false",
            "FLASHLOAN_KAMINO_ENABLED": "false",
            "FLASHLOAN_JUPITER_ENABLED": "false",
            "FLASHLOAN_HELIUS_ENABLED": "false",
            "LIVE_TRADING_ENABLED": "false",
            "PAPER_TRADING_ONLY": "true",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
        }
    )
    runner = Path(sys.executable).parent / "flashloan-bot"
    if not runner.is_file():
        raise ValueError("installed flashloan-bot entrypoint required")
    command = [
        str(runner),
        "paper-shadow",
        "--journal-path",
        str(out.resolve() / "paper-shadow.jsonl"),
        "--json",
    ]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            env=child,
            cwd=out.resolve(),
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        stdout, stderr, exit_code = (
            completed.stdout,
            completed.stderr,
            completed.returncode,
        )
        import json

        try:
            summary = json.loads(stdout)
        except (ValueError, UnicodeDecodeError):
            summary = {"status": "BLOCKED", "reason": "PAPER_OWNER_INVALID_OUTPUT"}
        status = (
            "COMPLETE"
            if exit_code == 0
            and isinstance(summary, dict)
            and summary.get("status") in {"healthy_idle", "paper_outcome"}
            else "BLOCKED"
        )
    except subprocess.TimeoutExpired:
        # subprocess.run kills/waits for the child before raising.
        stdout, stderr, exit_code = b"", b"", None
        summary, status = {"reason": "PAPER_OWNER_TIMEOUT"}, "BLOCKED"
    atomic_bytes(out / "paper.stdout.json", stdout)
    atomic_bytes(out / "paper.stderr.txt", stderr)
    receipt = seal(
        {
            "schema": "studious.paper-campaign.v2",
            "status": status,
            "process_started": True,
            "exit_code": exit_code,
            "rpc_hostname": endpoint.hostname,
            "configuration_sha256": digest(
                {"public_key": public_key, "rpc": rpc_url, "mode": "paper"}
            ),
            "elapsed_seconds": time.monotonic() - started,
            "paper_owner_summary": summary,
            "live_authorized": False,
            "private_key_required": False,
        }
    )
    save_json(out / "CAMPAIGN_RECEIPT.json", receipt)
    return receipt
