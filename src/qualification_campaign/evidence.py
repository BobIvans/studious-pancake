"""Campaign evidence facade over the existing durable raw stream authority.

No second SQLite factory. One campaign per journal; negative events and physical
attempt reservations survive restart. Replay uses retained bytes only.
"""

import json
import time
import os
import tempfile
import fcntl
from pathlib import Path
from dataclasses import asdict

from src.market.streams import RawStreamEvent, RecoverableStreamJournal
from .identity import CampaignManifest, canonical_bytes, digest


class CampaignEvidenceStore:
    def __init__(
        self,
        journal: RecoverableStreamJournal,
        manifest: CampaignManifest,
        *,
        wall_ns=time.time_ns,
    ):
        self.wall_ns = wall_ns
        self.journal = journal
        self.manifest = manifest
        db_path = journal.db.execute("PRAGMA database_list").fetchone()[2]
        self.lock_path = Path(db_path + ".campaign-lock")
        self.blob_dir = Path(db_path + ".blobs")
        retained = journal.events(available_at_ns=2**63 - 1)
        for e in retained:
            if e.partition != manifest.campaign_id:
                raise ValueError("CAMPAIGN_GENERATION_MISMATCH")
        if not retained:
            self.append(
                "campaign",
                {"kind": "manifest", "manifest": manifest.to_dict()},
                observed_at_ns=self.wall_ns(),
            )

    def append(
        self,
        source: str,
        payload: dict,
        *,
        observed_at_ns: int,
        available_at_ns: int | None = None,
    ) -> str:
        available = (
            max(observed_at_ns, self.wall_ns())
            if available_at_ns is None
            else available_at_ns
        )
        body = {**payload, "campaign_manifest_hash": self.manifest.campaign_id}
        stored = body
        encoded = canonical_bytes(body)
        if len(encoded) > 750_000:
            if len(encoded) > 16 * 1024 * 1024:
                raise ValueError("EVIDENCE_BLOB_TOO_LARGE")
            self.blob_dir.mkdir(exist_ok=True)
            name = digest(body)
            target = self.blob_dir / (name + ".json")
            if target.exists():
                if target.is_symlink() or target.read_bytes() != encoded:
                    raise ValueError("EVIDENCE_BLOB_HASH_MISMATCH")
            else:
                size = sum(f.stat().st_size for f in self.blob_dir.glob("*.json"))
                if size + len(encoded) > self.journal.max_payload_bytes:
                    raise ValueError("EVIDENCE_BLOB_STORAGE_BUDGET_EXHAUSTED")
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=self.blob_dir, suffix=".tmp", delete=False
                    ) as handle:
                        temporary = Path(handle.name)
                        handle.write(encoded)
                        handle.flush()
                        os.fsync(handle.fileno())
                    try:
                        os.link(temporary, target)
                    except FileExistsError:
                        if target.is_symlink() or target.read_bytes() != encoded:
                            raise ValueError("EVIDENCE_BLOB_HASH_MISMATCH")
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
                fd = os.open(self.blob_dir, os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            stored = {
                "kind": "blob_reference",
                "raw_payload_ref": name,
                "raw_payload_hash": name,
                "campaign_manifest_hash": self.manifest.campaign_id,
            }
        previous = [
            e
            for e in self.journal.events(available_at_ns=2**63 - 1)
            if e.source == source
        ]
        event = RawStreamEvent(
            source,
            self.manifest.campaign_id,
            1,
            previous[-1].cursor + 1 if previous else 1,
            available,
            observed_at_ns,
            source,
            "prequal.observation.v1",
            canonical_bytes(stored).decode(),
            digest(stored),
            previous[-1].block_hash if previous else "GENESIS",
        )
        self.journal.append(event)
        return event.identity

    def claim_attempt(self, profile) -> None:
        if (
            dict(self.manifest.source_generations).get(profile.profile_id)
            != profile.generation
        ):
            raise ValueError("SOURCE_GENERATION_MISMATCH")
        # Serialize campaign-cap reservations across cooperating processes.
        with self.lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                events = self.replay()
                spent = sum(
                    e.get("kind") == "attempt"
                    and e.get("provider_id") == profile.profile_id
                    for e in events
                )
                if spent >= profile.campaign_attempt_cap:
                    raise ValueError("CAMPAIGN_ATTEMPT_BUDGET_EXHAUSTED")
                self.append(
                    profile.profile_id,
                    {
                        "kind": "attempt",
                        "provider_id": profile.profile_id,
                        "source_generation": profile.generation,
                    },
                    observed_at_ns=self.wall_ns(),
                )
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def replay(self) -> tuple[dict, ...]:
        events = self.journal.events(available_at_ns=2**63 - 1)
        for e in events:
            if e.partition != self.manifest.campaign_id:
                raise ValueError("CAMPAIGN_GENERATION_MISMATCH")
            # The underlying journal is immutable by contract, verify hashes on replay.
            if digest(json.loads(e.payload_json)) != e.block_hash:
                raise ValueError("EVIDENCE_HASH_MISMATCH")
        return tuple(self.expand(e.payload_json) for e in events)

    def expand(self, serialized):
        body = json.loads(serialized)
        if body.get("kind") == "blob_reference":
            name = body["raw_payload_ref"]
            if (
                not isinstance(name, str)
                or len(name) != 64
                or any(c not in "0123456789abcdef" for c in name)
            ):
                raise ValueError("EVIDENCE_BLOB_REFERENCE_INVALID")
            target = self.blob_dir / (name + ".json")
            if target.is_symlink():
                raise ValueError("EVIDENCE_BLOB_REFERENCE_INVALID")
            body = json.loads(target.read_text())
            if digest(body) != name:
                raise ValueError("EVIDENCE_BLOB_HASH_MISMATCH")
        if body.get("campaign_manifest_hash") != self.manifest.campaign_id:
            raise ValueError("CAMPAIGN_GENERATION_MISMATCH")
        return body

    @property
    def head(self):
        return digest(
            [asdict(e) for e in self.journal.events(available_at_ns=2**63 - 1)]
        )


def redact_payload(value, headers):
    """Preserve public response shape, removing credential reflections only."""
    secrets: list[str] = []
    for name, token in (headers or {}).items():
        if name.lower() in ("authorization", "x-api-key") and token:
            secrets.extend((token, token.removeprefix("Bearer ")))
    forbidden = {
        "authorization",
        "apikey",
        "secret",
        "password",
        "accesstoken",
        "privatekey",
    }

    def clean(item):
        if isinstance(item, dict):
            return {
                k: (
                    "<redacted>"
                    if "".join(c for c in str(k).lower() if c.isalnum()) in forbidden
                    else clean(v)
                )
                for k, v in item.items()
            }
        if isinstance(item, list):
            return [clean(v) for v in item]
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, "<redacted>")
        return item

    return clean(value)
