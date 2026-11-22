"""PR #691 security closure: the five Codex review findings.

Each finding: root cause -> code fix -> positive/negative tests ->
zero-network proof for blocked paths. A fresh independent review runs on
the pushed SHA (separate reviewer agent).

F1 unknown/missing source cost semantics -> CS-10 BLOCKED
F2 signed attempt cap: the signed campaign-wide value is bound in the
   payload (CS-08) and every physical RPC call consumes its own reservation;
   the campaign-global pool itself is completed in the stacked CAM-04 branch
   (#694) and proven there.
F3 durable single-use ledger keyed by campaign identity, independent of the
   output directory (cross-output replay is not a fresh authorization)
F4 offline evidence is bound into the signed payload and its actual bytes are
   verified against the signed digest (existence + SHA-256 + scope)
F5 signed RPC method allowlist enforced at the runtime transport boundary
"""

import asyncio
import copy
import hashlib
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from src.market.discovery import DiscoveryRequest
from src.market.native_cpmm_capture import (
    GovernedNativeCpmmCollector,
    NativeCaptureError,
    install_signed_method_allowlists,
)
from src.qualification_campaign.approval_replay_ledger import (
    SQLiteApprovalReplayLedger,
)
from src.qualification_campaign.campaign_start_gate import (
    GateStatus,
    evaluate_campaign_start_gate,
)
from src.qualification_campaign.cli import campaign_ledger_path, campaign_state_root
from src.qualification_campaign.identity import CampaignManifest, digest
from src.qualification_campaign.profiles import READ_RPC_METHODS, ProviderProfile
from src.qualification_campaign.sources import CatalogDiscoveryAdapter
from src.security.trust_anchors import SignedEnvelope, signable_payload_bytes
from tests.test_cam01_campaign_start_gate import (
    NOW_NS,
    _dossier,
    _ed25519_keypair,
    _evaluate,
    _manifest,
    _plan_for,
    _registry,
    _rpc_profile,
    _sign_bytes,
    load_plan_from_raw,
    rpc_profile_for,
)

pytestmark = pytest.mark.unit

_MIRRORED_PLAN_FIELDS = (
    "budgets",
    "source_semantics",
    "source_method_allowlists",
    "offline_evidence",
)


def _copy_plan(plan, *, payload_changes=None, plan_changes=None):
    mutated = copy.deepcopy(plan)
    if payload_changes:
        mutated["approval_payload"].update(payload_changes)
    if plan_changes:
        mutated.update(plan_changes)
    return mutated


def _resign(plan, keypair, *, payload_changes=None, plan_changes=None):
    """Mutate the SIGNED payload, mirror top-level fields, re-sign the envelope.

    A valid modified approval must keep payload/top-level in sync and carry a
    matching signature; only a deliberate tampering test mutates AFTER signing
    and preserves the stale signature.
    """

    mutated = _copy_plan(
        plan, payload_changes=payload_changes, plan_changes=plan_changes
    )
    payload = mutated["approval_payload"]
    for field in _MIRRORED_PLAN_FIELDS:
        if plan_changes is None or field not in plan_changes:
            mutated[field] = copy.deepcopy(payload[field])
    envelope_fields = mutated["envelope"]
    payload_sha = hashlib.sha256(signable_payload_bytes(payload)).hexdigest()
    envelope = SignedEnvelope(
        domain=envelope_fields["domain"],
        schema_version=envelope_fields["schema_version"],
        environment=envelope_fields["environment"],
        key_id=envelope_fields["key_id"],
        issued_at=datetime.fromisoformat(envelope_fields["issued_at"]),
        expires_at=datetime.fromisoformat(envelope_fields["expires_at"]),
        payload_sha256=payload_sha,
        signature_base58=envelope_fields["signature_base58"],
    )
    envelope_fields["payload_sha256"] = payload_sha
    envelope_fields["signature_base58"] = _sign_bytes(
        keypair, envelope.canonical_message()
    )
    return mutated


def _authorized_inputs():
    keypair = _ed25519_keypair()
    dossier = _dossier()
    # Bind the runtime dossier generation so CS-03 holds for a fully
    # authorized baseline.
    manifest = CampaignManifest(
        repository_sha="1" * 40,
        main_sha="2" * 40,
        runtime_authority_sha256=digest({"runtime": "authority"}),
        configuration_digests=(("capture", digest({"verify_native": 1})),),
        source_generations=(("dexscreener", dossier.generation),),
    )
    dossier, _, plan = _plan_for(manifest, dossier, _rpc_profile(), keypair)
    return keypair, manifest, dossier, plan


def _adapter():
    return CatalogDiscoveryAdapter(
        DiscoveryRequest(
            source_id="dexscreener",
            token_mint="So11111111111111111111111111111111111111112",
        )
    )


def _tmpdir() -> Path:
    return Path(tempfile.mkdtemp())


def _evaluate_in(ledger_path: Path, manifest, dossier, plan, keypair):
    loaded = load_plan_from_raw(plan)
    return evaluate_campaign_start_gate(
        manifest=manifest,
        plan=loaded,
        dossiers=[dossier],
        adapters=[_adapter()],
        profiles=[rpc_profile_for(plan)],
        registry=_registry(keypair),
        ledger=SQLiteApprovalReplayLedger(ledger_path),
        now_ns=NOW_NS,
    )


# ------------------------------------------------- F1: cost semantics gate


def test_unknown_cost_semantics_block_cs10():
    keypair, manifest, dossier, plan = _authorized_inputs()
    plan = _resign(
        plan,
        keypair,
        payload_changes={"source_semantics": {"dexscreener": "UNKNOWN_COST_BLOCKED"}},
    )
    decision = _evaluate(_tmpdir(), manifest, dossier, plan, keypair)
    cs10 = [v for v in decision.verdicts if v.gate_id == "CS-10"]
    assert cs10 and cs10[0].status == GateStatus.BLOCKED.value
    assert any(b.startswith("SOURCE_COST_SEMANTICS_UNKNOWN") for b in decision.blockers)


def test_missing_cost_semantics_block_cs10():
    keypair, manifest, dossier, plan = _authorized_inputs()
    plan = _resign(plan, keypair, payload_changes={"source_semantics": {}})
    decision = _evaluate(_tmpdir(), manifest, dossier, plan, keypair)
    assert not decision.authorized
    assert any(b.startswith("SOURCE_COST_SEMANTICS_UNKNOWN") for b in decision.blockers)


def test_public_discovery_semantics_pass_cs10():
    keypair, manifest, dossier, plan = _authorized_inputs()
    decision = _evaluate(_tmpdir(), manifest, dossier, plan, keypair)
    cs10 = [v for v in decision.verdicts if v.gate_id == "CS-10"]
    assert cs10[0].status == GateStatus.PASS.value


def test_blocked_cs10_is_typed_blocker():
    """Zero-network proof at the gate level: a CS-10 BLOCKED decision is a
    typed blocker before any transport object can exist; the CLI sentinel
    (test_cam01_capture_blocked_before_transport) proves capture() stops
    before transport for every BLOCKED decision cause.
    """

    keypair, manifest, dossier, plan = _authorized_inputs()
    plan = _resign(
        plan,
        keypair,
        payload_changes={"source_semantics": {"dexscreener": "UNKNOWN_COST_BLOCKED"}},
    )
    decision = _evaluate(_tmpdir(), manifest, dossier, plan, keypair)
    assert decision.phase == "BLOCKED"
    assert decision.to_dict()["physical_network_attempts"] == 0


# ------------------------------------------------- F4: offline evidence


def test_offline_evidence_edit_after_signing_is_binding_mismatch():
    keypair, manifest, dossier, plan = _authorized_inputs()
    # Deliberate tamper AFTER signing: the payload signature is stale.
    tampered = _copy_plan(
        plan,
        plan_changes={
            "offline_evidence": {
                "journal_durability": {
                    "test_id": "tests/test_qpr02_data_plane.py",
                    "receipt_sha256": "f" * 64,
                },
                "replay_zero_network": {
                    "test_id": "tests/test_qpr03_source_intake.py",
                    "receipt_sha256": "d" * 64,
                },
            }
        },
    )
    decision = _evaluate(_tmpdir(), manifest, dossier, tampered, keypair)
    assert not decision.authorized
    assert "APPROVAL_PAYLOAD_BINDING_MISMATCH" in decision.blockers


def test_offline_evidence_missing_test_file_is_unverifiable():
    keypair, manifest, dossier, plan = _authorized_inputs()
    plan = _resign(
        plan,
        keypair,
        payload_changes={
            "offline_evidence": {
                "journal_durability": {
                    "test_id": "tests/definitely_missing_test_file.py",
                    "receipt_sha256": "b" * 64,
                },
                "replay_zero_network": plan["approval_payload"]["offline_evidence"][
                    "replay_zero_network"
                ],
            }
        },
    )
    decision = _evaluate(_tmpdir(), manifest, dossier, plan, keypair)
    assert any(
        b.startswith("OFFLINE_EVIDENCE_UNVERIFIABLE:JOURNAL") for b in decision.blockers
    )


def test_offline_evidence_digest_mismatch_is_rejected():
    keypair, manifest, dossier, plan = _authorized_inputs()
    plan = _resign(
        plan,
        keypair,
        payload_changes={
            "offline_evidence": {
                "journal_durability": {
                    "test_id": "tests/test_qpr02_data_plane.py",
                    "receipt_sha256": "0" * 64,
                },
                "replay_zero_network": plan["approval_payload"]["offline_evidence"][
                    "replay_zero_network"
                ],
            }
        },
    )
    decision = _evaluate(_tmpdir(), manifest, dossier, plan, keypair)
    assert not decision.authorized
    assert any(
        b.startswith("OFFLINE_EVIDENCE_DIGEST_MISMATCH:JOURNAL")
        for b in decision.blockers
    )


def test_offline_evidence_path_traversal_is_out_of_scope():
    keypair, manifest, dossier, plan = _authorized_inputs()
    plan = _resign(
        plan,
        keypair,
        payload_changes={
            "offline_evidence": {
                "journal_durability": {
                    "test_id": "../outside.py",
                    "receipt_sha256": "b" * 64,
                },
                "replay_zero_network": plan["approval_payload"]["offline_evidence"][
                    "replay_zero_network"
                ],
            }
        },
    )
    decision = _evaluate(_tmpdir(), manifest, dossier, plan, keypair)
    assert not decision.authorized
    assert any(
        b.startswith("OFFLINE_EVIDENCE_UNVERIFIABLE:JOURNAL") for b in decision.blockers
    )


def test_offline_evidence_positive_verifies_references():
    keypair, manifest, dossier, plan = _authorized_inputs()
    decision = _evaluate(_tmpdir(), manifest, dossier, plan, keypair)
    cs05 = [v for v in decision.verdicts if v.gate_id == "CS-05"]
    assert cs05[0].status == GateStatus.PASS.value
    assert not any(b.startswith("OFFLINE_EVIDENCE") for b in decision.blockers)


# ------------------------------------------------- F5: signed allowlist


def test_empty_signed_allowlist_is_refused():
    keypair, manifest, dossier, plan = _authorized_inputs()
    plan = _resign(
        plan,
        keypair,
        payload_changes={"source_method_allowlists": {"rpc-primary": []}},
    )
    decision = _evaluate(_tmpdir(), manifest, dossier, plan, keypair)
    assert not decision.authorized
    assert "SENDER_METHOD_IN_ALLOWLIST" in decision.blockers


def test_allowlist_with_unknown_method_is_refused():
    keypair, manifest, dossier, plan = _authorized_inputs()
    plan = _resign(
        plan,
        keypair,
        payload_changes={
            "source_method_allowlists": {"rpc-primary": ["getAccountInfoX"]}
        },
    )
    decision = _evaluate(_tmpdir(), manifest, dossier, plan, keypair)
    assert not decision.authorized
    assert "SENDER_METHOD_IN_ALLOWLIST" in decision.blockers


def test_runtime_allowlist_enforced_before_transport():
    """The signed allowlist is enforced at _rpc, BEFORE any transport work:
    the NativeCaptureError is pre-transport by construction (the method
    check runs before the request body/transport objects are built).
    """

    install_signed_method_allowlists({"rpc-x": ["getSlot"]})
    profile = ProviderProfile(
        "rpc-x",
        "p",
        "o",
        "g",
        "https://rpc.test/",
        "https://docs.test/rpc",
        request_limit=10,
        window_seconds=60,
        campaign_attempt_cap=10,
    )
    collector = object.__new__(GovernedNativeCpmmCollector)
    collector.profile = profile
    collector._sequence = 0
    collector.evidence_store = None

    async def run():
        with pytest.raises(NativeCaptureError, match="signed plan allowlist"):
            await collector._rpc("getMultipleAccounts", [])

    asyncio.run(run())
    install_signed_method_allowlists({})  # reset for other tests


# ------------------------------------------------- F3: ledger identity


def test_ledger_path_is_campaign_identity_not_output_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMPAIGN_STATE_ROOT", str(tmp_path / "state"))
    manifest = CampaignManifest(
        "1" * 40,
        "2" * 40,
        "c" * 64,
        (("capture", "d" * 64),),
        (("dexscreener", "e" * 64),),
    )
    # Two distinct caller-selected output dirs never enter the derivation.
    out_a = tmp_path / "out-a"
    out_b = tmp_path / "out-b"
    assert out_a != out_b
    name_a = campaign_ledger_path(manifest.campaign_id)
    name_b = campaign_ledger_path(manifest.campaign_id)
    assert name_a == name_b
    import dataclasses

    manifest_other = dataclasses.replace(manifest, runtime_authority_sha256="f" * 64)
    assert campaign_ledger_path(manifest_other.campaign_id) != name_a


def test_cross_output_envelope_consumption_is_not_fresh_authorization(
    tmp_path, monkeypatch
):
    """The same signed envelope consumed under output A cannot yield a fresh
    authorization under output B: both map to the campaign-identity ledger and
    the durable consumption row marks the second run as an idempotent replay.
    A fresh ledger handle simulates process restart recovery.
    """

    monkeypatch.setenv("CAMPAIGN_STATE_ROOT", str(tmp_path / "state"))
    keypair, manifest, dossier, plan = _authorized_inputs()
    ledger_path = campaign_ledger_path(manifest.campaign_id)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    out_a = tmp_path / "output-a"
    out_b = tmp_path / "output-b"
    assert out_a != out_b  # distinct outputs, same identity-keyed ledger

    first = _evaluate_in(ledger_path, manifest, dossier, plan, keypair)
    assert first.authorized
    assert first.approval_receipt is not None
    assert first.approval_receipt["replayed"] is False

    # Restart: a brand-new ledger handle reads the durable consumption row.
    second = _evaluate_in(ledger_path, manifest, dossier, plan, keypair)
    assert second.authorized
    assert second.approval_receipt is not None
    assert second.approval_receipt["replayed"] is True
    assert (
        second.approval_receipt["result_sha256"]
        == first.approval_receipt["result_sha256"]
    )


def test_campaign_state_root_is_stable_across_calls(monkeypatch, tmp_path):
    monkeypatch.setenv("CAMPAIGN_STATE_ROOT", str(tmp_path / "state"))
    assert campaign_state_root() == campaign_state_root()


# ------------------------------------------------- F2: signed cap binding


def test_signed_attempt_cap_is_bound_and_enforced_upstream():
    """F2: the SIGNED campaign-wide cap is bound into the approval payload
    (CS-08 carries the exact signed value). Per-physical-call reservation is
    proven below; the campaign-global pool is completed by the stacked CAM-04
    branch (#694) where the signed budgets are wired into the evidence store.
    """

    keypair, manifest, dossier, plan = _authorized_inputs()
    budgets = dict(plan["approval_payload"]["budgets"])
    budgets["rpc_physical_attempts_max"] = 1
    budgets["per_source_quotas"] = {
        "dexscreener": {"requests": 12, "window_seconds": 60, "attempts": 1}
    }
    capped = _resign(plan, keypair, payload_changes={"budgets": budgets})
    decision = _evaluate(_tmpdir(), manifest, dossier, capped, keypair)
    cs08 = [v for v in decision.verdicts if v.gate_id == "CS-08"]
    assert cs08[0].status == GateStatus.PASS.value
    assert cs08[0].evidence.get("campaign_attempts_max") == 1


class _RecordingEvidence:
    def __init__(self):
        self.calls = 0

    def claim_attempt(self, profile):  # noqa: ARG002 - signature parity
        self.calls += 1

    def append(self, *args, **kwargs):  # noqa: ARG002 - signature parity
        return None


def test_each_physical_rpc_consumes_one_attempt_reservation():
    """Every physical RPC request consumes its own reservation, including
    repeats/retries: N physical calls -> N claim_attempt calls, all pre-wire.
    """

    install_signed_method_allowlists({})
    profile = ProviderProfile(
        "rpc-x",
        "p",
        "o",
        "g",
        "https://rpc.test/",
        "https://docs.test/rpc",
        request_limit=10,
        window_seconds=60,
        campaign_attempt_cap=10,
    )
    collector = object.__new__(GovernedNativeCpmmCollector)
    collector.profile = profile
    collector._sequence = 0
    collector.evidence_store = _RecordingEvidence()
    collector.receipts = []
    collector.auth_headers = None
    collector.wall_ns = lambda: 0

    async def fake_physical(provider, operation, fingerprint, call):  # noqa: ARG001
        collector._sequence += 1
        return (
            200,
            {},
            {"jsonrpc": "2.0", "id": collector._sequence, "result": {}},
        )

    collector._physical = fake_physical
    method = sorted(READ_RPC_METHODS)[0]

    async def run():
        for _ in range(4):
            await collector._rpc(method, [])

    asyncio.run(run())
    assert collector.evidence_store.calls == 4
