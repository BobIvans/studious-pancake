"""Campaign evidence facade over the existing durable raw stream authority.

No second SQLite factory. One campaign per journal; negative events and physical
attempt reservations survive restart. Replay uses retained bytes only.
"""

import json
import time
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
            canonical_bytes(body).decode(),
            digest(body),
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
        return tuple(json.loads(e.payload_json) for e in events)

    @property
    def head(self):
        return digest(
            [asdict(e) for e in self.journal.events(available_at_ns=2**63 - 1)]
        )
