"""Immutable content-addressed provider envelopes, including negative evidence."""

from dataclasses import asdict, dataclass
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def text(value: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("nonempty normalized text required")


@dataclass(frozen=True)
class Evidence:
    source: str
    provider: str
    correlation_group: str
    generation: str
    observed_at: float
    response_hash: str
    request_hash: str
    slot_or_checkpoint: int | None = None
    negative_reason: str | None = None

    def __post_init__(self) -> None:
        for value in (
            self.source,
            self.provider,
            self.correlation_group,
            self.generation,
        ):
            text(value)
        for value in (self.response_hash, self.request_hash):
            if not re.fullmatch(r"[0-9a-f]{64}", value) or value == "0" * 64:
                raise ValueError("SHA256 evidence required")
        if not math.isfinite(self.observed_at) or self.observed_at <= 0:
            raise ValueError("invalid timestamp")
        if self.slot_or_checkpoint is not None and (
            type(self.slot_or_checkpoint) is not int or self.slot_or_checkpoint < 0
        ):
            raise ValueError("invalid chain position")

    def fresh(self, *, now: float, max_age: float, generation: str) -> bool:
        return (
            math.isfinite(now)
            and math.isfinite(max_age)
            and max_age > 0
            and self.generation == generation
            and self.negative_reason is None
            and 0 <= now - self.observed_at <= max_age
        )


class EvidenceStore:
    """Compressed immutable blobs; hashes verified on every replay."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def append(self, evidence: Evidence, payload: object) -> str:
        if digest(payload) != evidence.response_hash:
            raise ValueError("payload/evidence mismatch")
        record = {"evidence": asdict(evidence), "payload": payload}
        identity = digest(record)
        path = self.root / f"{identity}.json.gz"
        encoded = json.dumps(record, sort_keys=True, allow_nan=False).encode()
        try:
            with path.open("xb") as stream:
                stream.write(gzip.compress(encoded, mtime=0))
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if self.replay(identity) != record:
                raise ValueError("immutable evidence collision")
        index = self.root / (digest(asdict(evidence)) + ".ref.json")
        try:
            with index.open("x") as stream:
                json.dump({"record": identity}, stream)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if json.loads(index.read_text())["record"] != identity:
                raise ValueError("evidence metadata reused for different content")
        return identity

    def evidence_record(self, metadata_ref: str) -> dict:
        if not re.fullmatch(r"[0-9a-f]{64}", metadata_ref):
            raise ValueError("invalid evidence metadata reference")
        identity = json.loads((self.root / (metadata_ref + ".ref.json")).read_text())[
            "record"
        ]
        record = self.replay(identity)
        if digest(record["evidence"]) != metadata_ref:
            raise ValueError("evidence reference mismatch")
        return record

    def replay(self, identity: str) -> dict:
        if not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise ValueError("invalid evidence reference")
        record = json.loads(
            gzip.decompress((self.root / f"{identity}.json.gz").read_bytes())
        )
        if (
            digest(record) != identity
            or digest(record["payload"]) != record["evidence"]["response_hash"]
        ):
            raise ValueError("corrupt replay evidence")
        Evidence(**record["evidence"])
        return record
