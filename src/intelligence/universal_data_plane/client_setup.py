"""Client setup, health check and connection smoke test (OCA-W11B).

Writes ONLY a repo-local stdio config (never global config, never copies
credentials). ``smoke_test`` spawns the stdio server as a subprocess and runs
initialize → tools/list → one real query; "installed" and "connected" are
separate diagnostics.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

CONFIG_DIR = ".repo-intel"
SERVER_MODULE = "src.intelligence.universal_data_plane.mcp_server"


def write_local_config(
    repo_root: str | Path,
    *,
    state_root: str = "artifacts/intelligence",
) -> Path:
    """Write the repo-local stdio MCP config; returns the config path."""
    repo = Path(repo_root).resolve()
    target = repo / CONFIG_DIR / "mcp.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "mcpServers": {
            "studious-repo-intel": {
                "command": sys.executable,
                "args": [
                    "-m",
                    SERVER_MODULE,
                    "--repo",
                    str(repo),
                    "--state-root",
                    state_root,
                ],
                "transport": "stdio",
            }
        },
        "note": "repo-local config only; ChatGPT access is never implicit — connect explicitly",
    }
    target.write_text(
        json.dumps(config, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


def health_check(config_path: str | Path) -> dict[str, Any]:
    """Installed-vs-configured diagnostics (no server spawn)."""
    path = Path(config_path)
    if not path.exists():
        return {
            "installed": False,
            "connected": False,
            "reason": f"config missing: {path}",
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    command = payload["mcpServers"]["studious-repo-intel"]["command"]
    return {
        "installed": Path(command).exists(),
        "connected": False,
        "reason": "config present; run smoke_test for a live connection check",
    }


def smoke_test(
    config_path: str | Path,
    repo_root: str | Path,
    *,
    pythonpath: str | None = None,
) -> dict[str, Any]:
    """Live subprocess handshake: initialize → tools/list → one real query."""
    payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
    server = payload["mcpServers"]["studious-repo-intel"]
    proc_command = [server["command"], *server["args"]]
    env = None
    if pythonpath is not None:
        import os

        env = {**os.environ, "PYTHONPATH": pythonpath}
    proc = subprocess.Popen(
        proc_command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=str(repo_root),
        env=env,
    )
    stdin, stdout = proc.stdin, proc.stdout
    assert stdin is not None and stdout is not None

    def send(message: dict[str, Any]) -> dict[str, Any]:
        stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        stdin.flush()
        line = stdout.readline()
        return json.loads(line.decode("utf-8"))

    try:
        init = send({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        tools = send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tool_names = sorted(t["name"] for t in tools["result"]["tools"])
        sha_line = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"], text=True
        ).strip()
        query = send(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "repo_overview",
                    "arguments": {"repo_sha": sha_line},
                },
            }
        )
        query_ok = "error" not in query
    finally:
        stdin.close()
        proc.terminate()
    connected = (
        init.get("result", {}).get("serverInfo", {}).get("name")
        == "studious-repo-intel"
    )
    return {
        "installed": True,
        "connected": connected,
        "tools_listed": tool_names,
        "real_query_ok": query_ok,
        "diagnostic": (
            "connected client verified via initialize + tools/list + real query"
            if connected and query_ok
            else "server reachable but handshake incomplete"
        ),
    }
