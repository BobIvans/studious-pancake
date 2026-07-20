from __future__ import annotations

import dataclasses
import hashlib
import re
from typing import Any

REDACTION_VERSION = "redactor.v1"
REDACTED = "[REDACTED]"
SECRET_KEY_RE = re.compile(
    r"(private[_-]?key|keypair|seed|mnemonic|api[_-]?key|bearer|auth(orization)?|"
    r"token|hmac|secret|passphrase|signed[_-]?transaction|credential)",
    re.I,
)
SECRET_VALUE_RE = re.compile(
    r"(Bearer\s+[A-Za-z0-9._~+/=-]+|"
    r"https?://[^\s]+(?:api[_-]?key|token|key|secret)=[^\s&]+|"
    r"\b[1-9A-HJ-NP-Za-km-z]{80,}\b|"
    r"\b(?:seed|mnemonic|secret|token|api[_-]?key)[:=][^\s,;]+|"
    r"[A-Za-z0-9]*secret[A-Za-z0-9_=-]*)",
    re.I,
)
PATH_RE = re.compile(
    r"(/(?:home|Users|root|workspace)/[^\s,;]+(?:key|credential|secret)[^\s,;]*)",
    re.I,
)
SAFE_SCALARS = (type(None), bool, int, str)


class RedactionStats:
    def __init__(self) -> None:
        self.hits = 0


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(text: str) -> str:
    return digest_bytes(text.encode("utf-8", "replace"))[:16]


def _scrub_str(value: str, stats: RedactionStats, max_len: int) -> str:
    out = SECRET_VALUE_RE.sub(REDACTED, value)
    out = PATH_RE.sub(REDACTED, out)
    if out != value:
        stats.hits += 1
    if len(out) > max_len:
        stats.hits += 1
        return out[:max_len] + f"…[truncated:{len(out)}]"
    return out


def sanitize(
    obj: Any,
    *,
    max_depth: int = 8,
    max_keys: int = 128,
    max_str: int = 512,
    _depth: int = 0,
    stats: RedactionStats | None = None,
) -> Any:
    stats = stats or RedactionStats()
    if _depth > max_depth:
        stats.hits += 1
        return "[MAX_DEPTH]"
    if isinstance(obj, bytes):
        stats.hits += 1
        return {
            "bytes_digest": digest_bytes(obj),
            "bytes_len": len(obj),
            "redacted": True,
        }
    if isinstance(obj, BaseException):
        message = _scrub_str(str(obj), stats, max_str)
        return {
            "exception_type": type(obj).__name__,
            "message": message,
            "fingerprint": fingerprint(type(obj).__name__ + ":" + str(obj)),
        }
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        obj = dataclasses.asdict(obj)
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        count = 0
        for k, v in obj.items():
            count += 1
            if count > max_keys:
                stats.hits += 1
                out["[TRUNCATED_KEYS]"] = count
                break
            sk = _scrub_str(str(k), stats, max_str)
            if SECRET_KEY_RE.search(str(k)):
                stats.hits += 1
                out[sk] = REDACTED
            else:
                out[sk] = sanitize(
                    v,
                    max_depth=max_depth,
                    max_keys=max_keys,
                    max_str=max_str,
                    _depth=_depth + 1,
                    stats=stats,
                )
        return out
    if isinstance(obj, (list, tuple, set)):
        return [
            sanitize(
                v,
                max_depth=max_depth,
                max_keys=max_keys,
                max_str=max_str,
                _depth=_depth + 1,
                stats=stats,
            )
            for v in list(obj)[:max_keys]
        ]
    if isinstance(obj, SAFE_SCALARS):
        return _scrub_str(obj, stats, max_str) if isinstance(obj, str) else obj
    return _scrub_str(repr(obj), stats, max_str)


def sanitized_with_stats(obj: Any) -> tuple[Any, int]:
    stats = RedactionStats()
    value = sanitize(obj, stats=stats)
    return value, stats.hits
