"""Portable public/redacted campaign evidence, independently hashed and replayed."""

import argparse
from dataclasses import asdict
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

from src.market.streams import RawStreamEvent, RecoverableStreamJournal
from src.qualification_campaign.evidence import CampaignEvidenceStore
from src.qualification_campaign.identity import canonical_bytes, manifest_from_dict
from .cli import ROOT, replay


def audit_public_redacted(value):
    """Inspect structure only; never load environment or credential values."""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = "".join(c for c in str(key).lower() if c.isalnum())
            if normalized in {
                "authorization",
                "apikey",
                "privatekey",
                "password",
                "secret",
                "accesstoken",
                "httpsproxy",
            } and item not in (None, "<redacted>"):
                raise ValueError("NONPUBLIC_CREDENTIAL_FIELD_IN_EVIDENCE")
            if key == "semantic_headers" and any(
                str(pair[0]).lower() not in {"accept", "content-type", "user-agent"}
                for pair in item
            ):
                raise ValueError("PRIVATE_RECORDED_REQUEST_HEADER")
            audit_public_redacted(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            audit_public_redacted(item)


def export_archive(campaign, archive):
    manifest_bytes = (campaign / "campaign-manifest.json").read_bytes()
    manifest = manifest_from_dict(json.loads(manifest_bytes))
    journal = RecoverableStreamJournal(
        campaign / "campaign-evidence.sqlite", max_events=10_000
    )
    try:
        evidence = CampaignEvidenceStore(journal, manifest)
        expanded = evidence.replay()  # Verifies hashes, chains, blobs and generation.
        audit_public_redacted(expanded)
        events = journal.events(available_at_ns=2**63 - 1)
        files = {
            "campaign-manifest.json": manifest_bytes,
            "events.json": canonical_bytes([asdict(e) for e in events]),
            "capture-report.json": (campaign / "report.json").read_bytes(),
            "replay-report.json": canonical_bytes(replay(campaign)),
        }
        for event in events:
            body = json.loads(event.payload_json)
            if body.get("kind") == "blob_reference":
                name = body["raw_payload_ref"]
                if not re.fullmatch("[0-9a-f]{64}", name):
                    raise ValueError("BOUNDED_IMMUTABLE_BLOB_ID_REQUIRED")
                blob = (evidence.blob_dir / (name + ".json")).read_bytes()
                if hashlib.sha256(blob).hexdigest() != name:
                    raise ValueError("PORTABLE_BLOB_HASH_MISMATCH")
                files["blobs/" + name + ".json"] = blob
        index = {
            "schema_version": "gpr02.portable-evidence.v1",
            "campaign_id": manifest.campaign_id,
            "capture_repository_sha": manifest.repository_sha,
            "export_code_sha": subprocess.check_output(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
            ).strip(),
            "journal_head": evidence.head,
            "event_count": len(events),
            "files": {
                k: {"sha256": hashlib.sha256(v).hexdigest(), "bytes": len(v)}
                for k, v in sorted(files.items())
            },
            "audit": "PASS_PUBLIC_REDACTED_NO_PRIVATE_REQUEST_HEADERS",
            "excluded": [
                "credentials",
                "proxy-values",
                "authority-sqlite",
                "sqlite-journal",
                "db-locks",
                "venv",
                "caches",
            ],
        }
        files["INDEX.json"] = canonical_bytes(index)
    finally:
        journal.close()
    if sum(len(v) for v in files.values()) > 64_000_000:
        raise ValueError("PORTABLE_EVIDENCE_TOTAL_BUDGET_EXHAUSTED")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("xb") as target:
        with gzip.GzipFile(filename="", fileobj=target, mode="wb", mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                for name, value in sorted(files.items()):
                    member = tarfile.TarInfo(name)
                    member.size = len(value)
                    member.mode = 0o644
                    tar.addfile(member, io.BytesIO(value))
    return {
        "archive": archive.name,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "compressed_bytes": archive.stat().st_size,
        "campaign_id": manifest.campaign_id,
        "capture_repository_sha": manifest.repository_sha,
        "audit": index["audit"],
    }


def replay_archive(archive):
    if archive.stat().st_size > 16_000_000:
        raise ValueError("PORTABLE_COMPRESSED_BUDGET_EXHAUSTED")
    files: dict[str, bytes] = {}
    size = 0
    with tarfile.open(archive, "r|gz") as tar:
        for member in tar:
            if (
                not member.isfile()
                or member.name in files
                or len(files) >= 1000
                or not (
                    member.name
                    in {
                        "INDEX.json",
                        "campaign-manifest.json",
                        "events.json",
                        "capture-report.json",
                        "replay-report.json",
                    }
                    or re.fullmatch(r"blobs/[0-9a-f]{64}\.json", member.name)
                )
                or not 0 <= member.size <= 16_000_000
            ):
                raise ValueError("UNSAFE_OR_UNBOUNDED_PORTABLE_MEMBER")
            size += member.size
            if size > 64_000_000:
                raise ValueError("PORTABLE_EVIDENCE_TOTAL_BUDGET_EXHAUSTED")
            stream = tar.extractfile(member)
            if stream is None:
                raise ValueError("PORTABLE_REGULAR_MEMBER_REQUIRED")
            value = stream.read(member.size + 1)
            if len(value) != member.size:
                raise ValueError("PORTABLE_MEMBER_SIZE_MISMATCH")
            files[member.name] = value
    index = json.loads(files["INDEX.json"])
    if index.get("schema_version") != "gpr02.portable-evidence.v1" or set(
        index["files"]
    ) != set(files) - {"INDEX.json"}:
        raise ValueError("PORTABLE_INDEX_SCHEMA_OR_MEMBERS_MISMATCH")
    for name, pin in index["files"].items():
        if (
            len(files[name]) != pin["bytes"]
            or hashlib.sha256(files[name]).hexdigest() != pin["sha256"]
        ):
            raise ValueError("PORTABLE_MEMBER_HASH_MISMATCH")
    manifest = manifest_from_dict(json.loads(files["campaign-manifest.json"]))
    if (
        manifest.campaign_id != index["campaign_id"]
        or manifest.repository_sha != index["capture_repository_sha"]
    ):
        raise ValueError("PORTABLE_CAMPAIGN_GENERATION_MISMATCH")
    with tempfile.TemporaryDirectory(prefix="gpr02-replay-") as temporary:
        output = Path(temporary)
        (output / "campaign-manifest.json").write_bytes(files["campaign-manifest.json"])
        journal = RecoverableStreamJournal(
            output / "campaign-evidence.sqlite", max_events=10_000
        )
        try:
            events = json.loads(files["events.json"])
            if len(events) != index["event_count"] or len(events) > 10_000:
                raise ValueError("PORTABLE_EVENT_COUNT_MISMATCH")
            for row in events:
                journal.append(RawStreamEvent(**row))
            blobs = output / "campaign-evidence.sqlite.blobs"
            for name, value in files.items():
                if name.startswith("blobs/"):
                    blobs.mkdir(exist_ok=True)
                    (blobs / name.removeprefix("blobs/")).write_bytes(value)
            evidence = CampaignEvidenceStore(journal, manifest)
            audit_public_redacted(evidence.replay())
            if evidence.head != index["journal_head"]:
                raise ValueError("PORTABLE_JOURNAL_HEAD_MISMATCH")
        finally:
            journal.close()
        result = replay(output)
    if canonical_bytes(result) != files["replay-report.json"]:
        raise ValueError("PORTABLE_DETERMINISTIC_REPLAY_MISMATCH")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("export", "replay"))
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args(argv)
    result = (
        export_archive(args.campaign, args.archive)
        if args.command == "export"
        else replay_archive(args.archive)
    )
    print(
        json.dumps(
            (
                result
                if args.command == "export"
                else {
                    k: result[k]
                    for k in (
                        "campaign_id",
                        "capture_repository_sha",
                        "replay",
                        "discovery_candidate_count",
                        "quotes_measured",
                    )
                }
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
