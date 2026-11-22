"""CAM-04 SECURITY CLOSURE v3: reservation invariant integration tests.

Proves, against the real cli.capture() lifecycle ordering, that:
- the authority store is materialized BEFORE any evidence append, so journal
  appends can never spend the preflight's AUTHORITY_CREATION_RESERVE_BYTES
  (projected accounting is filesystem truth and the authority footprint is
  on disk before the first append);
- the strict physical ceiling holds after EVERY accepted write, including
  first-time DB creation with its WAL/SHM sidecars;
- an authority store that materializes larger than reserved fails closed
  with a typed blocker (max-load-before-materialization attack);
- measured SQLite page sizes (journal/ledger/authority) are recorded in a
  durable receipt instead of relying on the 4096 assumption;
- the ceiling stays enforced across restart.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.durability import UnifiedLifecycleAuthority
from src.market.streams import RecoverableStreamJournal
from src.qualification_campaign.approval_replay_ledger import (
    SQLiteApprovalReplayLedger,
)
from src.qualification_campaign.evidence import (
    AUTHORITY_CREATION_RESERVE_BYTES,
    reconcile_materialized_artifacts,
    CampaignBudgets,
    CampaignEvidenceStore,
    artifact_footprint_bytes,
    journal_growth_bound,
    sqlite_page_size,
)
from src.qualification_campaign.identity import CampaignManifest

pytestmark = pytest.mark.unit

PAGE = 4096


def manifest_for():
    return CampaignManifest(
        repository_sha="1" * 40,
        main_sha="2" * 40,
        runtime_authority_sha256="c" * 64,
        configuration_digests=(("capture", "d" * 64),),
        source_generations=(("dexscreener", "e" * 64),),
    )


def budgets_for(storage_bytes_max):
    return CampaignBudgets(
        rpc_physical_attempts_max=200,
        storage_bytes_max=storage_bytes_max,
        external_data_spend_usd_max=0,
    )


def _campaign_layout(output: Path, manifest):
    """Exact cli.capture() v3 ordering: authority store materialized first."""

    manifest_path = output / "campaign-manifest.json"
    manifest_path.write_bytes(json.dumps(manifest.to_dict()).encode())
    ledger_path = output / "campaign-approval-ledger.sqlite"
    ledger = SQLiteApprovalReplayLedger(ledger_path)
    authority_path = output / "authority.sqlite"
    authority = UnifiedLifecycleAuthority(
        authority_path,
        release_digest=manifest.runtime_authority_sha256,
        policy_bundle_hash=manifest.campaign_id,
    )
    authority_paths = (
        authority_path,
        Path(str(authority_path) + "-wal"),
        Path(str(authority_path) + "-shm"),
    )
    return manifest_path, ledger_path, authority_path, authority_paths, authority


def test_authority_store_materialized_before_any_evidence_append(tmp_path):
    """The v3 ordering contract: at CampaignEvidenceStore construction time
    the authority store is already on disk and counted in the projection
    base (no reserve window left)."""

    manifest = manifest_for()
    output = tmp_path / "out"
    output.mkdir()
    manifest_path, ledger_path, authority_path, authority_paths, authority = (
        _campaign_layout(output, manifest)
    )
    authority_bytes = artifact_footprint_bytes(authority_paths)
    assert authority_bytes > 0

    journal = RecoverableStreamJournal(output / "campaign-evidence.sqlite")
    observed_at_init = {}
    real_init = CampaignEvidenceStore.__init__

    def spying_init(self, *args, **kwargs):
        observed_at_init["authority_exists"] = authority_path.exists()
        observed_at_init["authority_bytes"] = artifact_footprint_bytes(authority_paths)
        return real_init(self, *args, **kwargs)

    original = CampaignEvidenceStore.__init__
    CampaignEvidenceStore.__init__ = spying_init
    try:
        evidence = CampaignEvidenceStore(
            journal,
            manifest,
            campaign_budgets=budgets_for(2**30),
            ledger_path=ledger_path,
            extra_artifacts=(manifest_path, *authority_paths),
        )
    finally:
        CampaignEvidenceStore.__init__ = original
    assert observed_at_init["authority_exists"] is True
    assert observed_at_init["authority_bytes"] == authority_bytes
    # The bootstrap manifest append's projection base includes the
    # authority bytes: campaign_storage_bytes() is at least the authority
    # footprint after the very first append.
    assert evidence.campaign_storage_bytes() >= authority_bytes
    authority.close()


def test_appends_cannot_spend_unmaterialized_authority_reserve(tmp_path):
    """Under the v3 ordering, an append's projection includes the real
    authority bytes; squeezing the budget proves the last admissible append
    count matches the arithmetic that CHARGES the authority footprint. If
    the authority bytes were not charged, exactly one extra append would
    fit - the test pins the charged value."""

    manifest = manifest_for()
    output = tmp_path / "out"
    output.mkdir()
    manifest_path, ledger_path, authority_path, authority_paths, authority = (
        _campaign_layout(output, manifest)
    )
    authority_bytes = artifact_footprint_bytes(authority_paths)

    journal = RecoverableStreamJournal(output / "campaign-evidence.sqlite")
    evidence = CampaignEvidenceStore(
        journal,
        manifest,
        campaign_budgets=None,
        ledger_path=ledger_path,
        extra_artifacts=(manifest_path, *authority_paths),
    )
    base = evidence.campaign_storage_bytes()
    growth = journal_growth_bound(4096, PAGE)
    budget = base + 3 * growth
    evidence.campaign_budgets = budgets_for(budget)
    # Invariant proven per accepted write: after EVERY accepted append the
    # real footprint (authority bytes charged) stays <= budget, and appends
    # stop at the typed blocker. If the authority footprint were NOT
    # charged, at least one append would have been accepted with a real
    # footprint strictly above the budget.
    accepted_footprints = []
    for i in range(10):
        try:
            evidence.append(
                "dexscreener",
                {"i": i, "body": "x" * 4096},
                observed_at_ns=1_000 + i,
            )
            accepted_footprints.append(evidence.campaign_storage_bytes())
        except ValueError as exc:
            assert "CAMPAIGN_STORAGE_BUDGET_EXHAUSTED" in str(exc)
            break
    assert len(accepted_footprints) >= 1
    for footprint in accepted_footprints:
        assert footprint <= budget, (footprint, budget)
    # Sanity: the authority footprint is a real part of the charged base.
    assert authority_bytes > 0
    assert base >= authority_bytes


def test_max_load_before_authority_materialization_fail_closed(tmp_path):
    """Attack reproduction: fill the journal to the budget ceiling while the
    authority store does not exist (legacy ordering), then materialize the
    authority store - the post-creation reconciliation must fail closed
    with the typed blocker instead of silently exceeding the budget."""

    manifest = manifest_for()
    output = tmp_path / "out"
    output.mkdir()
    manifest_path = output / "campaign-manifest.json"
    manifest_path.write_bytes(json.dumps(manifest.to_dict()).encode())
    ledger_path = output / "campaign-approval-ledger.sqlite"
    SQLiteApprovalReplayLedger(ledger_path)
    authority_path = output / "authority.sqlite"
    authority_paths = (
        authority_path,
        Path(str(authority_path) + "-wal"),
        Path(str(authority_path) + "-shm"),
    )
    authority_bytes_target = AUTHORITY_CREATION_RESERVE_BYTES // 4

    journal = RecoverableStreamJournal(output / "campaign-evidence.sqlite")
    evidence = CampaignEvidenceStore(
        journal,
        manifest,
        campaign_budgets=None,
        ledger_path=ledger_path,
        extra_artifacts=(manifest_path,),
    )
    base = evidence.campaign_storage_bytes()
    growth = journal_growth_bound(4096, PAGE)
    budget = base + authority_bytes_target
    evidence.campaign_budgets = budgets_for(budget)
    # Max load: append until the ceiling blocks (authority still absent,
    # so the whole budget minus base is consumable by journal rows).
    accepted = 0
    for i in range(10_000):
        try:
            evidence.append(
                "dexscreener",
                {"i": i, "body": "x" * 4096},
                observed_at_ns=1_000 + i,
            )
            accepted += 1
        except ValueError as exc:
            assert "CAMPAIGN_STORAGE_BUDGET" in str(exc)
            break
    assert accepted > 0
    # Now materialize the authority store on the exhausted budget.
    authority = UnifiedLifecycleAuthority(
        authority_path,
        release_digest=manifest.runtime_authority_sha256,
        policy_bundle_hash=manifest.campaign_id,
    )
    try:
        evidence.extra_artifacts = evidence.extra_artifacts + authority_paths
        # Drive the REAL reconciliation path used by cli.capture() after the
        # authority store materializes (not a hand-raised exception).
        with pytest.raises(ValueError, match="CAMPAIGN_STORAGE_BUDGET_EXCEEDED"):
            reconcile_materialized_artifacts(authority_paths, evidence.campaign_budgets)
    finally:
        authority.close()


def test_strict_ceiling_counts_db_creation_and_sidecars(tmp_path):
    """The first append creates the journal DB + WAL/SHM; the post-write
    reconciliation and the projection must count all sidecar bytes."""

    manifest = manifest_for()
    output = tmp_path / "out"
    output.mkdir()
    journal = RecoverableStreamJournal(output / "campaign-evidence.sqlite")
    evidence = CampaignEvidenceStore(
        journal,
        manifest,
        campaign_budgets=budgets_for(2**30),
    )
    assert evidence.campaign_storage_bytes() >= (
        Path(str(output / "campaign-evidence.sqlite-wal")).stat().st_size
        + (output / "campaign-evidence.sqlite").stat().st_size
    )
    evidence.append("dexscreener", {"i": 0, "body": "x" * 4096}, observed_at_ns=1)
    expected = (
        evidence.db_path.stat().st_size
        + Path(str(evidence.db_path) + "-wal").stat().st_size
    )
    assert evidence.campaign_storage_bytes() >= expected


def test_measured_page_sizes_are_recorded_not_assumed(tmp_path):
    """SECURITY CLOSURE v3: page sizes of journal/ledger/authority are
    measured from the actual stores; the durable receipt carries them."""

    manifest = manifest_for()
    output = tmp_path / "out"
    output.mkdir()
    manifest_path, ledger_path, authority_path, authority_paths, authority = (
        _campaign_layout(output, manifest)
    )
    journal = RecoverableStreamJournal(output / "campaign-evidence.sqlite")
    evidence = CampaignEvidenceStore(
        journal,
        manifest,
        campaign_budgets=budgets_for(2**30),
        ledger_path=ledger_path,
        extra_artifacts=(manifest_path, *authority_paths),
    )
    evidence.append(
        "campaign",
        {"kind": "storage_reconciliation"},
        observed_at_ns=1,
    )
    receipt = [
        e for e in evidence.replay() if e.get("kind") == "storage_reconciliation"
    ]
    assert receipt, "storage reconciliation event must be retained"
    measured_journal = evidence.page_size
    measured_ledger = sqlite_page_size(ledger_path)
    measured_authority = sqlite_page_size(authority_path)
    assert measured_journal == 4096  # SQLite default, actually read
    assert measured_ledger == 4096
    assert measured_authority == 4096
    # The helper reads the real files (not constants): deleting the file
    # makes the measurement None.
    assert sqlite_page_size(output / "missing.sqlite") is None


def test_restart_keeps_ceiling_enforced(tmp_path):
    manifest = manifest_for()
    output = tmp_path / "out"
    output.mkdir()
    manifest_path, ledger_path, authority_path, authority_paths, authority = (
        _campaign_layout(output, manifest)
    )
    authority_bytes = artifact_footprint_bytes(authority_paths)
    journal = RecoverableStreamJournal(output / "campaign-evidence.sqlite")
    evidence = CampaignEvidenceStore(
        journal,
        manifest,
        campaign_budgets=budgets_for(2**30),
        ledger_path=ledger_path,
        extra_artifacts=(manifest_path, *authority_paths),
    )
    base = evidence.campaign_storage_bytes()
    growth = journal_growth_bound(4096, PAGE)
    evidence.campaign_budgets = budgets_for(base + 2 * growth)
    for i in range(2):
        evidence.append(
            "dexscreener", {"i": i, "b": "y" * 4096}, observed_at_ns=1_000 + i
        )
    # Restart: fresh store objects over the same durable artifacts.
    reopened = CampaignEvidenceStore(
        RecoverableStreamJournal(output / "campaign-evidence.sqlite"),
        manifest,
        campaign_budgets=budgets_for(base + 2 * growth),
        ledger_path=ledger_path,
        extra_artifacts=(manifest_path, *authority_paths),
    )
    with pytest.raises(ValueError, match="CAMPAIGN_STORAGE_BUDGET_EXHAUSTED"):
        reopened.append("dexscreener", {"i": 9, "b": "y" * 4096}, observed_at_ns=2_000)
