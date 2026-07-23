"""Bounded recorded provider/economic input for the canonical paper root."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib import resources
import json
from pathlib import Path
from typing import Mapping

from .model import PaperCandidate, RECORDING_SCHEMA, RecordingError, strict_int

DEFAULT_RECORDING_RESOURCE = "paper_recorded_cycle.json"
DEFAULT_MAX_BYTES = 256 * 1024
DEFAULT_MAX_ITEMS = 64


@dataclass(frozen=True, slots=True)
class RecordedBatch:
    source_name: str
    source_digest: str
    candidates: tuple[PaperCandidate, ...]


class BoundedRecordedBatchSource:
    def __init__(
        self, path: Path | None = None, *, max_bytes: int = DEFAULT_MAX_BYTES,
        max_items: int = DEFAULT_MAX_ITEMS,
    ) -> None:
        if not 0 < max_bytes <= 16 * 1024 * 1024:
            raise ValueError("max_bytes must be within 1..16777216")
        if not 0 < max_items <= 10_000:
            raise ValueError("max_items must be within 1..10000")
        self.path, self.max_bytes, self.max_items = path, max_bytes, max_items

    def load(self) -> RecordedBatch:
        raw, source_name = self._read_bytes()
        try:
            payload = json.loads(
                raw.decode("utf-8"),
                parse_constant=lambda value: _raise(f"non-finite JSON: {value}"),
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RecordingError("recording must be valid UTF-8 JSON") from exc
        if not isinstance(payload, Mapping) or payload.get("schema_version") != RECORDING_SCHEMA:
            raise RecordingError("recording schema mismatch")
        items = payload.get("candidates")
        if not isinstance(items, list) or not items:
            raise RecordingError("recording must contain candidates")
        if len(items) > self.max_items:
            raise RecordingError("recording candidate limit exceeded")
        candidates, seen = [], set()
        for index, item in enumerate(items):
            if not isinstance(item, Mapping):
                raise RecordingError(f"candidate {index} must be an object")
            candidate = candidate_from_mapping(item)
            if candidate.candidate_id in seen:
                raise RecordingError("duplicate candidate_id")
            seen.add(candidate.candidate_id)
            candidates.append(candidate)
        return RecordedBatch(source_name, hashlib.sha256(raw).hexdigest(), tuple(candidates))

    def _read_bytes(self) -> tuple[bytes, str]:
        if self.path is None:
            raw = resources.files("src.resources").joinpath(DEFAULT_RECORDING_RESOURCE).read_bytes()
            name = f"package:{DEFAULT_RECORDING_RESOURCE}"
        else:
            target = Path(self.path)
            if target.is_symlink():
                raise RecordingError("recording path cannot be a symlink")
            try:
                if target.stat().st_size > self.max_bytes:
                    raise RecordingError("recording byte limit exceeded")
                raw = target.read_bytes()
            except OSError as exc:
                raise RecordingError("recording path is not readable") from exc
            name = str(target)
        if len(raw) > self.max_bytes:
            raise RecordingError("recording byte limit exceeded")
        return raw, name


def candidate_from_mapping(item: Mapping[str, object]) -> PaperCandidate:
    fields = set(PaperCandidate.__dataclass_fields__)
    missing, unknown = sorted(fields - set(item)), sorted(set(item) - fields)
    if missing or unknown:
        raise RecordingError(
            f"candidate fields mismatch missing={','.join(missing)} unknown={','.join(unknown)}"
        )
    ints = fields - {
        "candidate_id", "provider_evidence_digest", "compiled_message_digest",
        "simulation_message_digest",
    }
    values = {
        name: strict_int(item[name], name) if name in ints else str(item[name])
        for name in fields
    }
    return PaperCandidate(**values)


def digest_config_file(path: Path | None, *, max_bytes: int = DEFAULT_MAX_BYTES) -> str:
    if path is None:
        return hashlib.sha256(b"canonical-paper-default-config").hexdigest()
    target = Path(path)
    if target.is_symlink():
        raise RecordingError("config path cannot be a symlink")
    try:
        if target.stat().st_size > max_bytes:
            raise RecordingError("config byte limit exceeded")
        raw = target.read_bytes()
    except OSError as exc:
        raise RecordingError("config path is not readable") from exc
    if len(raw) > max_bytes:
        raise RecordingError("config byte limit exceeded")
    return hashlib.sha256(raw).hexdigest()


def _raise(message: str) -> None:
    raise RecordingError(message)
