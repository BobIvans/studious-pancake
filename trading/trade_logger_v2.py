"""Append-only deterministic log writer for paper trader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from utils.io import append_jsonl


def _segment_key(event: dict[str, Any], paths: dict[str, Path | str | bool]) -> str | None:
    if not paths.get("segment_by_day"):
        return None
    ts = str(event.get("ts") or event.get("timestamp") or event.get("signal_ts") or "")
    return ts[:10] if len(ts) >= 10 else "active"


def log_signal(event: dict[str, Any], paths: dict[str, Path]) -> None:
    append_jsonl(paths["signals"], event, segment_key=_segment_key(event, paths))


def _mask_sensitive_data(event: dict[str, Any]) -> dict[str, Any]:
    """Mask sensitive data like keys in logs."""
    masked = event.copy()
    sensitive_fields = ["private_key", "secret", "api_key", "wallet_key"]
    for field in sensitive_fields:
        if field in masked and isinstance(masked[field], str):
            if len(masked[field]) > 8:
                masked[field] = masked[field][:4] + "*" * (len(masked[field]) - 8) + masked[field][-4:]
            else:
                masked[field] = "***"
    return masked

def log_trade(event: dict[str, Any], paths: dict[str, Path]) -> None:
    masked_event = _mask_sensitive_data(event)
    append_jsonl(paths["trades"], masked_event, segment_key=_segment_key(event, paths))
