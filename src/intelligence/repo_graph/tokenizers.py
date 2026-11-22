"""Tokenizer adapters with labelled fallback (OCA-W4B).

A real target tokenizer is used when configured AND locally available;
otherwise a deterministic character-class estimator runs, clearly labelled as
an estimate with uncertainty. No network calls, no model APIs — this module
never contacts a service (indexing stays LLM-free per the indexing contract;
token accounting is measurement only).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Protocol

FALLBACK_ID = "char-class-estimator-v1"
FALLBACK_UNCERTAINTY = "±15% (heuristic estimate, not a model tokenizer)"


class TokenizerAdapter(Protocol):
    def identity(self) -> str: ...

    def uncertainty(self) -> str: ...

    def count(self, data: bytes) -> int: ...


class CharClassEstimator:
    """Deterministic heuristic estimator: word/symbol/CJK class weights.

    Clearly labelled as an estimate; deterministic for identical bytes.
    """

    _WORD_RE = re.compile(rb"[A-Za-z0-9_]+")
    _CJK_RE = re.compile(rb"[\xe4-\xe9][\x80-\xbf]{2}")

    def identity(self) -> str:
        return FALLBACK_ID

    def uncertainty(self) -> str:
        return FALLBACK_UNCERTAINTY

    def count(self, data: bytes) -> int:
        words = len(self._WORD_RE.findall(data))
        cjk = len(self._CJK_RE.findall(data))
        remaining = max(len(data) - words * 5 - cjk * 3, 0)
        return words + cjk + remaining // 4


class TiktokenAdapter:
    """Real tokenizer, used only when explicitly configured.

    Encoding loads come from the local tiktoken cache; a cache miss raises and
    the caller falls back to the labelled estimator (never a silent estimate
    pretending to be a real tokenizer).
    """

    def __init__(self, encoding_name: str) -> None:
        import tiktoken  # noqa: F401 - import guarded by factory

        self._encoding_name = encoding_name
        self._encoding = tiktoken.get_encoding(encoding_name)

    def identity(self) -> str:
        return f"tiktoken:{self._encoding_name}"

    def uncertainty(self) -> str:
        return "exact for the configured tokenizer profile"

    def count(self, data: bytes) -> int:
        return len(self._encoding.encode(data.decode("utf-8", "replace")))


def resolve_tokenizer(
    profile: str | None, *, allow_real: bool = True
) -> tuple[TokenizerAdapter, dict[str, Any]]:
    """Resolve a tokenizer profile into (adapter, metadata).

    ``profile=None`` → labelled fallback. ``profile="tiktoken:<name>"`` → real
    tokenizer when importable and locally cached; any failure degrades to the
    fallback with ``degraded_reason`` recorded (never silent).
    """
    if profile and profile.startswith("tiktoken:") and allow_real:
        name = profile.split(":", 1)[1]
        try:
            adapter: TokenizerAdapter = TiktokenAdapter(name)
            return adapter, {
                "tokenizer": adapter.identity(),
                "tokenizer_uncertainty": adapter.uncertainty(),
                "degraded_reason": None,
            }
        except Exception as exc:  # noqa: BLE001 - explicit degradation
            fallback = CharClassEstimator()
            return fallback, {
                "tokenizer": fallback.identity(),
                "tokenizer_uncertainty": fallback.uncertainty(),
                "degraded_reason": f"TIKTOKEN_UNAVAILABLE: {type(exc).__name__}",
            }
    fallback = CharClassEstimator()
    return fallback, {
        "tokenizer": fallback.identity(),
        "tokenizer_uncertainty": fallback.uncertainty(),
        "degraded_reason": None if profile is None else "REAL_TOKENIZER_NOT_CONFIGURED",
    }


def signature_body_hashes(
    data: bytes, start_byte: int, end_byte: int
) -> dict[str, str]:
    """Independent signature/body hashes for a symbol range (W4B §1).

    The signature is the first line of the range; the body is the remainder.
    Deterministic for identical bytes; used for early-cutoff invalidation and
    skeleton construction.
    """
    text = data[start_byte:end_byte].decode("utf-8", "replace")
    first_newline = text.find("\n")
    if first_newline == -1:
        signature, body = text, ""
    else:
        signature, body = text[:first_newline], text[first_newline + 1 :]
    return {
        "signature_hash": hashlib.sha256(signature.encode("utf-8")).hexdigest(),
        "body_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }
