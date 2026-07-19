from __future__ import annotations
import base64, hashlib, json, re
from typing import Any
BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
def raw_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
def require_base58(value: str, label: str) -> str:
    if not isinstance(value, str) or not BASE58_RE.match(value):
        raise ValueError(f"invalid base58 {label}")
    return value
def require_base64(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"invalid base64 {label}")
    try: base64.b64decode(value, validate=True)
    except Exception as exc: raise ValueError(f"invalid base64 {label}") from exc
    return value
