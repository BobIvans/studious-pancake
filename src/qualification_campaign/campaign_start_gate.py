"""Executable CAMPAIGN_START_V1 gate: operator authorization before transport.

The capture path previously started intake immediately after creating its
runtime manifest; CAMPAIGN_START_V1 existed only as a manual mapping doc.
This module makes the gate fail-closed and executable BEFORE any transport
object, DNS lookup or physical request can exist:

- Phase ``PREFLIGHT_PASS``: every pre-network-verifiable CS-01..CS-10 gate
  holds, the operator's Ed25519 envelope verifies against a currently valid
  trust anchor, the exact approved manifest/profile/budget binding matches
  runtime, and the offline durability/replay evidence pins are present.
- Phase ``CAPTURE_AUTHORIZED``: permits only the bounded, read-only requests
  described by the signed approval.  It is explicitly NOT a campaign
  qualification PASS: CS-06 stays ``CS06_PENDING_CAPTURE`` until real,
  non-synthetic capture evidence with the required quorum exists in the
  evidence journal.
- Any missing, mismatched or unverifiable input returns phase ``BLOCKED``
  with typed blockers and ``physical_network_attempts == 0``.

The operator signature is an EXTERNAL Ed25519 envelope verified through the
canonical trust-anchor owner (:mod:`src.security.trust_anchors`).  Single-use
consumption of the external envelope is enforced durably through the
PR-201 replay ledger owner (see
``SQLiteApprovalReplayLedger.reserve_external_envelope``), keyed by the
canonical envelope fingerprint, so a replayed envelope cannot authorize a
second operation with a fresh internal nonce.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Mapping, Sequence, cast

from src.release_gate.asymmetric_qualification import (
    AsymmetricQualificationError,
    signed_envelope_from_dict,
    trust_registry_from_dict,
)
from src.security.trust_anchors import (
    SignedEnvelope,
    TrustAnchorRegistry,
    TrustUsage,
    signable_payload_bytes,
)
from .approval_replay_ledger import (
    ApprovalReceipt,
    ApprovalReplayError,
    SQLiteApprovalReplayLedger,
    external_envelope_consumption_key,
)
from .identity import CampaignManifest, digest

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .profiles import ProviderProfile
    from .sources import CatalogDiscoveryAdapter, SourceDossier

APPROVAL_DOMAIN = "flashloan-bot/campaign-start-operator-approval.v1"
APPROVAL_PAYLOAD_SCHEMA = "prequal.campaign-start-approval-payload.v1"
DECISION_SCHEMA = "prequal.campaign-start-decision.v1"
PLAN_SCHEMA_VERSION = "prequal.campaign-plan.v2"
GATE_SET = "CAMPAIGN_START_V1"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_MAX_PLAN_BYTES = 1_000_000

# Words that must never appear in an approved source/method allowlist.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# The signed allowlist can only narrow this reviewed sender-free read set.
try:
    from src.qualification_campaign.profiles import (
        READ_RPC_METHODS as _ALLOWED_RUNTIME_RPC_METHODS,
    )
except ImportError:  # pragma: no cover - direct-module import shape
    _ALLOWED_RUNTIME_RPC_METHODS = frozenset()

_FORBIDDEN_METHOD_TOKENS = (
    "send",
    "submit",
    "sign",
    "borrow",
    "repay",
    "deploy",
    "createaccount",
    "relay",
    "airdrop",
)

_BLOCKING_GATES = tuple(f"CS-{index:02d}" for index in range(1, 11))


class GatePhase(StrEnum):
    PREFLIGHT_PASS = "PREFLIGHT_PASS"
    CAPTURE_AUTHORIZED = "CAPTURE_AUTHORIZED"
    BLOCKED = "BLOCKED"


class GateStatus(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    PENDING_CAPTURE = "CS06_PENDING_CAPTURE"


@dataclass(frozen=True)
class GateVerdict:
    gate_id: str
    status: str
    evidence: Mapping[str, object]


@dataclass(frozen=True)
class GateDecision:
    phase: GatePhase
    verdicts: tuple[GateVerdict, ...]
    blockers: tuple[str, ...]
    approval_receipt: Mapping[str, object] | None
    manifest_digest: str
    campaign_label: str

    @property
    def authorized(self) -> bool:
        return self.phase is GatePhase.CAPTURE_AUTHORIZED

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": DECISION_SCHEMA,
            "gate_set": GATE_SET,
            "phase": self.phase.value,
            "campaign_label": self.campaign_label,
            "approved_manifest_digest": self.manifest_digest,
            "verdicts": [
                {
                    "gate_id": v.gate_id,
                    "status": v.status,
                    "evidence": dict(v.evidence),
                }
                for v in self.verdicts
            ],
            "blockers": list(self.blockers),
            "approval_receipt": (
                dict(self.approval_receipt) if self.approval_receipt else None
            ),
            "physical_network_attempts": 0,
        }


def consumption_key_for_envelope(envelope: SignedEnvelope, payload_sha256: str) -> str:
    """Canonical durable consumption key for one external signed envelope."""

    return external_envelope_consumption_key(
        envelope_domain=envelope.domain,
        schema_version=envelope.schema_version,
        key_id=envelope.key_id,
        issued_at_utc=envelope.issued_at.astimezone(timezone.utc).isoformat(),
        expires_at_utc=envelope.expires_at.astimezone(timezone.utc).isoformat(),
        payload_sha256=payload_sha256,
        signature_base58=envelope.signature_base58,
    )


@dataclass(frozen=True)
class CampaignPlan:
    """Versioned, schema-strict view of an approved campaign plan document.

    The loader mirrors the documented V2 contract (label/mode/budgets/
    approval) without importing artifacts from any other branch: the
    ``campaign_id``-shaped human identifier lives in ``campaign_label`` and
    the cryptographic manifest identity stays bound by digest only.
    """

    campaign_label: str
    environment: str
    approved_manifest_digest: str
    repository_sha: str
    main_sha: str
    runtime_authority_sha256: str
    policy_bundle_sha256: str
    trust_registry_generation: str
    configuration_digests: dict[str, str]
    source_generations: dict[str, str]
    profiles_digests: dict[str, str]
    budgets: dict[str, object]
    retention: Mapping[str, object]
    capture_window_seconds: int
    discovery_only: bool
    source_semantics: dict[str, str]
    source_method_allowlists: dict[str, list[str]]
    offline_evidence: Mapping[str, object]
    approval_payload: Mapping[str, object]
    envelope: Mapping[str, object]
    raw: Mapping[str, object]

    def expected_approval_payload(self) -> dict[str, object]:
        return {
            "schema_version": APPROVAL_PAYLOAD_SCHEMA,
            "gate_set": GATE_SET,
            "campaign_label": self.campaign_label,
            "environment": self.environment,
            "mode": "CAPTURE_ONLY",
            "approved_manifest_digest": self.approved_manifest_digest,
            "repository_sha": self.repository_sha,
            "main_sha": self.main_sha,
            "runtime_authority_sha256": self.runtime_authority_sha256,
            "policy_bundle_sha256": self.policy_bundle_sha256,
            "trust_registry_generation": self.trust_registry_generation,
            "configuration_digests": self.configuration_digests,
            "source_generations": self.source_generations,
            "profiles_digests": self.profiles_digests,
            "budgets": self.budgets,
            "retention": dict(self.retention),
            "capture_window_seconds": self.capture_window_seconds,
            "discovery_only": True,
            "source_semantics": self.source_semantics,
            "source_method_allowlists": self.source_method_allowlists,
            # SECURITY CLOSURE (Codex finding 4): the offline evidence
            # references are part of the signed binding — editing them after
            # signing is a binding mismatch, not an accepted hex check.
            "offline_evidence": dict(self.offline_evidence),
        }


def load_campaign_plan(path: Path) -> CampaignPlan:
    """Strictly parse and validate an approved campaign plan document."""

    raw_bytes = Path(path).read_bytes()
    if len(raw_bytes) > _MAX_PLAN_BYTES:
        raise ValueError("CAMPAIGN_PLAN_TOO_LARGE")
    raw = json.loads(raw_bytes)
    if not isinstance(raw, dict):
        raise ValueError("CAMPAIGN_PLAN_INVALID")
    if raw.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise ValueError("CAMPAIGN_PLAN_SCHEMA_UNSUPPORTED")
    if raw.get("gate_set") != GATE_SET:
        raise ValueError("CAMPAIGN_PLAN_GATE_SET_MISMATCH")
    if raw.get("mode") != "CAPTURE_ONLY":
        raise ValueError("CAMPAIGN_PLAN_MODE_INVALID")
    if raw.get("discovery_only") is not True:
        raise ValueError("CAMPAIGN_PLAN_MUST_BE_DISCOVERY_ONLY")

    def _digest_field(key: str, length: int, label: str) -> str:
        value = raw.get(key)
        if not isinstance(value, str) or not re.fullmatch(
            f"^[0-9a-f]{{{length}}}$", value
        ):
            raise ValueError(f"CAMPAIGN_PLAN_{label}_INVALID")
        return value

    def _digest_map(key: str, label: str) -> dict[str, str]:
        value = raw.get(key)
        if not isinstance(value, dict) or not value:
            raise ValueError(f"CAMPAIGN_PLAN_{label}_REQUIRED")
        out: dict[str, str] = {}
        for name, item in value.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"CAMPAIGN_PLAN_{label}_NAME_INVALID")
            if not isinstance(item, str) or not _HEX64.fullmatch(item):
                raise ValueError(f"CAMPAIGN_PLAN_{label}_DIGEST_INVALID")
            out[name] = item
        return out

    for field in ("campaign_label", "environment"):
        if not isinstance(raw.get(field), str) or not raw[field].strip():
            raise ValueError(f"CAMPAIGN_PLAN_{field.upper()}_REQUIRED")
    trust_generation = raw.get("trust_registry_generation")
    if not isinstance(trust_generation, str) or not trust_generation.strip():
        raise ValueError("CAMPAIGN_PLAN_TRUST_GENERATION_REQUIRED")

    budgets = raw.get("budgets")
    if not isinstance(budgets, dict):
        raise ValueError("CAMPAIGN_PLAN_BUDGETS_REQUIRED")
    attempts_max = budgets.get("rpc_physical_attempts_max")
    storage_max = budgets.get("storage_bytes_max")
    spend_max = budgets.get("external_data_spend_usd_max")
    if not isinstance(attempts_max, int) or not 0 < attempts_max <= 10_000:
        raise ValueError("CAMPAIGN_PLAN_ATTEMPT_BUDGET_UNBOUNDED")
    if not isinstance(storage_max, int) or not 0 < storage_max <= 2**30:
        raise ValueError("CAMPAIGN_PLAN_STORAGE_BUDGET_UNBOUNDED")
    if spend_max != 0:
        raise ValueError("CAMPAIGN_PLAN_PAID_SPEND_FORBIDDEN")
    per_source = budgets.get("per_source_quotas")
    if not isinstance(per_source, dict) or not per_source:
        raise ValueError("CAMPAIGN_PLAN_PER_SOURCE_QUOTAS_REQUIRED")
    for name, quota in per_source.items():
        if not isinstance(quota, dict):
            raise ValueError("CAMPAIGN_PLAN_PER_SOURCE_QUOTA_INVALID")
        if not isinstance(quota.get("requests"), int) or quota["requests"] <= 0:
            raise ValueError("CAMPAIGN_PLAN_QUOTA_REQUESTS_UNBOUNDED")
        if (
            not isinstance(quota.get("window_seconds"), int)
            or quota["window_seconds"] <= 0
        ):
            raise ValueError("CAMPAIGN_PLAN_QUOTA_WINDOW_INVALID")
        if (
            not isinstance(quota.get("attempts"), int)
            or not 0 < quota["attempts"] <= attempts_max
        ):
            raise ValueError("CAMPAIGN_PLAN_QUOTA_ATTEMPTS_UNBOUNDED")

    window = raw.get("capture_window_seconds")
    if not isinstance(window, int) or not 0 < window <= 7 * 86400:
        raise ValueError("CAMPAIGN_PLAN_CAPTURE_WINDOW_UNBOUNDED")

    retention = raw.get("retention")
    if not isinstance(retention, dict):
        raise ValueError("CAMPAIGN_PLAN_RETENTION_REQUIRED")

    offline = raw.get("offline_evidence")
    if not isinstance(offline, dict):
        raise ValueError("CAMPAIGN_PLAN_OFFLINE_EVIDENCE_REQUIRED")
    for entry in ("journal_durability", "replay_zero_network"):
        item = offline.get(entry)
        if not isinstance(item, dict) or not isinstance(item.get("test_id"), str):
            raise ValueError(f"CAMPAIGN_PLAN_OFFLINE_EVIDENCE_{entry.upper()}_MISSING")

    semantics = raw.get("source_semantics")
    if not isinstance(semantics, dict):
        raise ValueError("CAMPAIGN_PLAN_SOURCE_SEMANTICS_REQUIRED")
    allowed_semantics = {"PUBLIC_DISCOVERY", "UNKNOWN_COST_BLOCKED"}
    for name, value in semantics.items():
        if value not in allowed_semantics:
            raise ValueError("CAMPAIGN_PLAN_SOURCE_SEMANTICS_UNKNOWN")

    allowlists_raw = raw.get("source_method_allowlists", {})
    allowlists: dict[str, list[str]] = {}
    if not isinstance(allowlists_raw, dict):
        raise ValueError("CAMPAIGN_PLAN_METHOD_ALLOWLISTS_INVALID")
    for profile_id, methods in allowlists_raw.items():
        if not isinstance(methods, list) or not all(
            isinstance(m, str) and m.strip() for m in methods
        ):
            raise ValueError("CAMPAIGN_PLAN_METHOD_ALLOWLISTS_INVALID")
        allowlists[str(profile_id)] = list(methods)

    approval = raw.get("approval_payload")
    envelope = raw.get("envelope")
    if not isinstance(approval, dict) or not isinstance(envelope, dict):
        raise ValueError("CAMPAIGN_PLAN_APPROVAL_REQUIRED")

    return CampaignPlan(
        campaign_label=str(raw["campaign_label"]),
        environment=str(raw["environment"]),
        approved_manifest_digest=_digest_field(
            "approved_manifest_digest", 64, "APPROVED_MANIFEST_DIGEST"
        ),
        repository_sha=_digest_field("repository_sha", 40, "REPOSITORY_SHA"),
        main_sha=_digest_field("main_sha", 40, "MAIN_SHA"),
        runtime_authority_sha256=_digest_field(
            "runtime_authority_sha256", 64, "RUNTIME_AUTHORITY"
        ),
        policy_bundle_sha256=_digest_field("policy_bundle_sha256", 64, "POLICY_BUNDLE"),
        trust_registry_generation=trust_generation,
        configuration_digests=_digest_map("configuration_digests", "CONFIGURATION"),
        source_generations=_digest_map("source_generations", "SOURCE_GENERATIONS"),
        profiles_digests=_digest_map("profiles_digests", "PROFILES"),
        budgets=dict(budgets),
        retention=retention,
        capture_window_seconds=window,
        discovery_only=True,
        source_semantics=dict(semantics),
        source_method_allowlists=allowlists,
        offline_evidence=offline,
        approval_payload=approval,
        envelope=envelope,
        raw=raw,
    )


def _verdict(gate_id: str, status: GateStatus, **evidence: object) -> GateVerdict:
    return GateVerdict(gate_id, status.value, evidence)


def _semantics_allowlist_clean(plan: CampaignPlan) -> bool:
    for methods in plan.source_method_allowlists.values():
        if not methods:
            # SECURITY CLOSURE (Codex finding 5): an empty signed allowlist
            # would silently disable the runtime restriction; refuse it.
            return False
        for method in methods:
            lowered = str(method).lower()
            if any(token in lowered for token in _FORBIDDEN_METHOD_TOKENS):
                return False
            if method not in _ALLOWED_RUNTIME_RPC_METHODS:
                # The signed list may only narrow the reviewed read set; an
                # unknown method name cannot be honored at the transport.
                return False
    return True


def evaluate_campaign_start_gate(
    *,
    manifest: CampaignManifest,
    plan: CampaignPlan,
    dossiers: Sequence["SourceDossier"],
    adapters: Sequence["CatalogDiscoveryAdapter"],
    profiles: Sequence["ProviderProfile"],
    registry: TrustAnchorRegistry | None,
    ledger: SQLiteApprovalReplayLedger,
    now_ns: int,
) -> GateDecision:
    """Fail-closed pre-network CAMPAIGN_START_V1 evaluation.

    Performs no I/O beyond the approval ledger database and raises nothing
    for expected negative outcomes: every missing/mismatched input becomes a
    typed blocker and ``physical_network_attempts == 0``.
    """

    blockers: list[str] = []
    verdicts: list[GateVerdict] = []
    evaluated_at = datetime.fromtimestamp(now_ns / 10**9, tz=timezone.utc)

    # ---- CS-01: manifest binds current release/policy/trust identity -------
    cs01_blockers = []
    if manifest.campaign_id != plan.approved_manifest_digest:
        cs01_blockers.append("APPROVAL_MANIFEST_DIGEST_MISMATCH")
    if manifest.repository_sha != plan.repository_sha:
        cs01_blockers.append("APPROVED_REPOSITORY_SHA_MISMATCH")
    if manifest.main_sha != plan.main_sha:
        cs01_blockers.append("APPROVED_MAIN_SHA_STALE")
    if manifest.runtime_authority_sha256 != plan.runtime_authority_sha256:
        cs01_blockers.append("RUNTIME_AUTHORITY_DIGEST_MISMATCH")
    if dict(manifest.configuration_digests) != plan.configuration_digests:
        cs01_blockers.append("CONFIGURATION_GENERATION_MISMATCH")
    if dict(manifest.source_generations) != plan.source_generations:
        cs01_blockers.append("SOURCE_GENERATION_MISMATCH")
    if cs01_blockers:
        blockers.extend(cs01_blockers)
        verdicts.append(_verdict("CS-01", GateStatus.BLOCKED, reasons=cs01_blockers))
    else:
        verdicts.append(
            _verdict(
                "CS-01",
                GateStatus.PASS,
                manifest_digest=manifest.campaign_id,
                trust_registry_generation=plan.trust_registry_generation,
            )
        )

    # ---- CS-02: sender/signer/submission unreachable -----------------------
    safety = cast(dict[str, bool], manifest.to_dict()["safety"])
    plan_methods_clean = _semantics_allowlist_clean(plan)
    if (
        any(safety.values())
        or plan.raw.get("mode") != "CAPTURE_ONLY"
        or not plan_methods_clean
    ):
        reason = (
            "SAFETY_BOUNDARY_OPEN"
            if any(safety.values())
            else (
                "SENDER_METHOD_IN_ALLOWLIST"
                if not plan_methods_clean
                else "MODE_INVALID"
            )
        )
        blockers.append(reason)
        verdicts.append(_verdict("CS-02", GateStatus.BLOCKED, reason=reason))
    else:
        verdicts.append(_verdict("CS-02", GateStatus.PASS, signer_reachable=False))

    # ---- CS-03: dossier + generation + quota owner for every source --------
    cs03_reasons = []
    dossier_ids = {d.source_id for d in dossiers}
    profile_ids = {p.profile_id for p in profiles}
    per_source_quotas = cast(
        dict[str, object], plan.budgets.get("per_source_quotas", {})
    )
    for d in dossiers:
        if plan.source_generations.get(d.source_id) != d.generation:
            cs03_reasons.append(f"DOSSIER_GENERATION_MISMATCH:{d.source_id}")
        if not isinstance(per_source_quotas.get(d.source_id), dict):
            cs03_reasons.append(f"PER_SOURCE_QUOTA_MISSING:{d.source_id}")
        try:
            d.require_current(now_ns)
        except ValueError:
            cs03_reasons.append(f"SOURCE_DOCS_STALE:{d.source_id}")
    for p in profiles:
        if plan.profiles_digests.get(p.profile_id) != digest(asdict(p)):
            cs03_reasons.append(f"PROFILE_GENERATION_MISMATCH:{p.profile_id}")
    if dossier_ids & profile_ids:
        cs03_reasons.append("SOURCE_AND_PROVIDER_IDS_COLLIDE")
    if cs03_reasons:
        blockers.extend(cs03_reasons)
        verdicts.append(_verdict("CS-03", GateStatus.BLOCKED, reasons=cs03_reasons))
    else:
        verdicts.append(_verdict("CS-03", GateStatus.PASS, sources=sorted(dossier_ids)))

    # ---- CS-04: discovery never promoted to exact edge ---------------------
    promotion_leak = [
        d.source_id
        for d in dossiers
        if d.classification != "DISCOVERY_ONLY"
        or set(d.capabilities) != {"candidate-discovery"}
    ]
    if promotion_leak or plan.discovery_only is not True:
        blockers.append("DISCOVERY_PROMOTION_LEAK")
        verdicts.append(_verdict("CS-04", GateStatus.BLOCKED, sources=promotion_leak))
    else:
        verdicts.append(
            _verdict("CS-04", GateStatus.PASS, classification="DISCOVERY_ONLY")
        )

    # ---- CS-05/CS-07: offline durability + zero-network replay evidence ----
    offline = plan.offline_evidence
    journal_entry = offline.get("journal_durability")
    replay_entry = offline.get("replay_zero_network")
    journal_entry = journal_entry if isinstance(journal_entry, dict) else {}
    replay_entry = replay_entry if isinstance(replay_entry, dict) else {}
    journal_receipt = journal_entry.get("receipt_sha256")
    replay_receipt = replay_entry.get("receipt_sha256")
    durability_ok = isinstance(journal_receipt, str) and bool(
        _HEX64.fullmatch(journal_receipt)
    )
    replay_ok = isinstance(replay_receipt, str) and bool(
        _HEX64.fullmatch(replay_receipt)
    )
    if not durability_ok:
        blockers.append("OFFLINE_JOURNAL_EVIDENCE_MISSING")
    if not replay_ok:
        blockers.append("OFFLINE_REPLAY_EVIDENCE_MISSING")
    # SECURITY CLOSURE (Codex finding 4): a hash-shaped string proves nothing.
    # The referenced artifact must exist inside the authorized repository scope
    # and its ACTUAL bytes must match the signed receipt digest. Missing,
    # fabricated, modified and out-of-scope references all fail closed.
    for kind, entry in (
        ("JOURNAL", journal_entry),
        ("REPLAY", replay_entry),
    ):
        test_id = entry.get("test_id")
        receipt = entry.get("receipt_sha256")
        if not isinstance(test_id, str) or not test_id:
            continue
        relative = Path(test_id)
        if relative.is_absolute() or ".." in relative.parts:
            blockers.append(f"OFFLINE_EVIDENCE_UNVERIFIABLE:{kind}:{test_id}")
            continue
        repo_test = (_REPO_ROOT / relative).resolve()
        if _REPO_ROOT not in repo_test.parents and repo_test != _REPO_ROOT:
            # Symlink/relative traversal cannot escape the authorized scope.
            blockers.append(f"OFFLINE_EVIDENCE_UNVERIFIABLE:{kind}:{test_id}")
            continue
        if not repo_test.is_file():
            blockers.append(f"OFFLINE_EVIDENCE_UNVERIFIABLE:{kind}:{test_id}")
            continue
        if isinstance(receipt, str) and _HEX64.fullmatch(receipt):
            actual = hashlib.sha256(repo_test.read_bytes()).hexdigest()
            if actual != receipt:
                blockers.append(f"OFFLINE_EVIDENCE_DIGEST_MISMATCH:{kind}:{test_id}")
    verdicts.append(
        _verdict(
            "CS-05",
            GateStatus.PASS if durability_ok else GateStatus.BLOCKED,
            test_id=journal_entry.get("test_id"),
        )
    )
    verdicts.append(
        _verdict(
            "CS-07",
            GateStatus.PASS if replay_ok else GateStatus.BLOCKED,
            test_id=replay_entry.get("test_id"),
        )
    )

    # ---- CS-06: real capture evidence — cannot be pre-network fact ---------
    # The first capture is only permitted by CAPTURE_AUTHORIZED; qualification
    # (and quorum) verdicts stay pending until journal evidence exists.
    verdicts.append(
        _verdict(
            "CS-06",
            GateStatus.PENDING_CAPTURE,
            note="REQUIRES_REAL_CAPTURE_HUMAN_GATED",
            quorum="PENDING",
        )
    )

    # ---- CS-08: physical quotas bounded, retries consume budget ------------
    attempts_max = cast(int, plan.budgets["rpc_physical_attempts_max"])
    per_source = cast(dict[str, object], plan.budgets["per_source_quotas"])
    quota_total = sum(
        int(cast(int, cast(dict[str, object], quota)["attempts"]))
        for quota in per_source.values()
    )
    if quota_total > attempts_max:
        blockers.append("PER_SOURCE_ATTEMPTS_EXCEED_CAMPAIGN_CAP")
        verdicts.append(_verdict("CS-08", GateStatus.BLOCKED, quota_total=quota_total))
    else:
        verdicts.append(
            _verdict(
                "CS-08",
                GateStatus.PASS,
                campaign_attempts_max=attempts_max,
                storage_bytes_max=plan.budgets["storage_bytes_max"],
            )
        )

    # ---- CS-09: current external docs/source pins --------------------------
    cs09_reasons = []
    for d, a in zip(dossiers, adapters):
        contract_digest = digest(a.schema_contract())
        if contract_digest != d.schema_fingerprint:
            cs09_reasons.append(f"SCHEMA_FINGERPRINT_MISMATCH:{d.source_id}")
        if not _HEX64.fullmatch(d.docs_sha256):
            cs09_reasons.append(f"DOCS_PIN_MISSING:{d.source_id}")
    if cs09_reasons:
        blockers.extend(cs09_reasons)
        verdicts.append(_verdict("CS-09", GateStatus.BLOCKED, reasons=cs09_reasons))
    else:
        verdicts.append(_verdict("CS-09", GateStatus.PASS, checked="docs_pins_current"))

    # ---- CS-10: unknown cost/semantics fail closed -------------------------
    if cast(int, plan.budgets["external_data_spend_usd_max"]) != 0:
        blockers.append("PAID_SPEND_NOT_ZERO")
        verdicts.append(_verdict("CS-10", GateStatus.BLOCKED, spend="NONZERO"))
    else:
        # SECURITY CLOSURE (Codex finding 1): cost semantics are executable
        # policy. A source whose signed semantics are missing or explicitly
        # UNKNOWN_COST_BLOCKED can carry unverified spend; under a zero-spend
        # budget the capture must be BLOCKED, never reported as PASS.
        unknown = [
            d.source_id
            for d in dossiers
            if plan.source_semantics.get(d.source_id) != "PUBLIC_DISCOVERY"
        ]
        if unknown:
            reasons = [f"SOURCE_COST_SEMANTICS_UNKNOWN:{sid}" for sid in unknown]
            blockers.extend(reasons)
            verdicts.append(
                _verdict(
                    "CS-10",
                    GateStatus.BLOCKED,
                    spend=0,
                    unknown_cost_blocked=unknown,
                    reasons=reasons,
                )
            )
        else:
            verdicts.append(
                _verdict("CS-10", GateStatus.PASS, spend=0, unknown_cost_blocked=())
            )

    # ---- Operator approval: Ed25519 envelope + durable single-use ----------
    approval_receipt: dict[str, object] | None = None
    try:
        envelope = signed_envelope_from_dict(plan.envelope)
    except (AsymmetricQualificationError, ValueError):
        envelope = None
        blockers.append("APPROVAL_ENVELOPE_MALFORMED")

    expected_payload = plan.expected_approval_payload()
    if envelope is not None and plan.approval_payload != expected_payload:
        blockers.append("APPROVAL_PAYLOAD_BINDING_MISMATCH")
    if envelope is not None and envelope.domain != APPROVAL_DOMAIN:
        blockers.append("APPROVAL_ENVELOPE_DOMAIN_MISMATCH")

    if envelope is not None and not blockers:
        if registry is None:
            blockers.append("OPERATOR_TRUST_ANCHOR_MISSING")
        else:
            if registry.generation != plan.trust_registry_generation:
                blockers.append("TRUST_REGISTRY_GENERATION_MISMATCH")
            else:
                payload_bytes = signable_payload_bytes(plan.approval_payload)
                result = registry.verify(
                    envelope,
                    payload_bytes,
                    usage=TrustUsage.OPERATOR_APPROVAL,
                    evaluated_at=evaluated_at,
                    expected_domain=APPROVAL_DOMAIN,
                    expected_environment=plan.environment,
                )
                if not result.verified:
                    blockers.extend(result.blockers)
                else:
                    consumption_key = consumption_key_for_envelope(
                        envelope, result.payload_sha256
                    )
                    request_hash = digest(
                        {
                            "campaign_manifest": manifest.campaign_id,
                            "gate_set": GATE_SET,
                            "trust_registry_generation": registry.generation,
                        }
                    )
                    try:
                        reservation = ledger.reserve_external_envelope(
                            consumption_key=consumption_key,
                            envelope_domain=envelope.domain,
                            key_id=envelope.key_id,
                            payload_sha256=result.payload_sha256,
                            signature_base58=envelope.signature_base58,
                            envelope_expires_at_ns=int(
                                envelope.expires_at.timestamp() * 10**9
                            ),
                            operation_id=manifest.campaign_id,
                            request_hash=request_hash,
                            now_ns=now_ns,
                        )
                        receipt_payload: dict[str, object] = {
                            "decision_phase": GatePhase.CAPTURE_AUTHORIZED.value,
                            "campaign_manifest": manifest.campaign_id,
                            "campaign_label": plan.campaign_label,
                            "envelope_consumption_key": consumption_key,
                            "trust_registry_generation": registry.generation,
                            "gate_set": GATE_SET,
                        }
                        authorization = ledger.finalize_external_envelope(
                            consumption_key=consumption_key,
                            operation_id=manifest.campaign_id,
                            request_hash=request_hash,
                            receipt=ApprovalReceipt.from_payload(
                                "operator_campaign_start_approval", receipt_payload
                            ),
                            now_ns=now_ns,
                        )
                        approval_receipt = {
                            "consumption_key": consumption_key,
                            "key_id": envelope.key_id,
                            "result_sha256": authorization.receipt.result_sha256,
                            "replayed": authorization.replayed,
                        }
                    except ApprovalReplayError as exc:
                        blockers.append(
                            "APPROVAL_ENVELOPE_REPLAY_PROTECTION:" + exc.failure
                        )

    preflight_blockers = [
        blocker
        for blocker in blockers
        if not blocker.startswith(
            (
                "APPROVAL_ENVELOPE",
                "APPROVAL_PAYLOAD",
                "OPERATOR_TRUST",
                "TRUST_REGISTRY",
                "CRYPTOGRAPHIC_SIGNATURE",
                "SIGNED_",
                "TRUST_ANCHOR",
            )
        )
    ]
    if not blockers:
        phase = GatePhase.CAPTURE_AUTHORIZED
    elif not preflight_blockers:
        # Every pre-network CS gate holds; only the operator approval is
        # missing/unverifiable.  Fail closed, but record the honest phase.
        phase = GatePhase.PREFLIGHT_PASS
    else:
        phase = GatePhase.BLOCKED
    return GateDecision(
        phase=phase,
        verdicts=tuple(verdicts),
        blockers=tuple(dict.fromkeys(blockers)),
        approval_receipt=approval_receipt,
        manifest_digest=manifest.campaign_id,
        campaign_label=plan.campaign_label,
    )


def load_trust_registry(path: Path | None) -> TrustAnchorRegistry | None:
    """Load an optional operator trust registry file; None = no anchors."""

    if path is None:
        return None
    raw = json.loads(Path(path).read_bytes())
    try:
        return trust_registry_from_dict(raw)
    except AsymmetricQualificationError as exc:
        raise ValueError("OPERATOR_TRUST_REGISTRY_INVALID:" + str(exc)) from exc


__all__ = [
    "APPROVAL_DOMAIN",
    "GATE_SET",
    "GateDecision",
    "GatePhase",
    "GateStatus",
    "GateVerdict",
    "CampaignPlan",
    "evaluate_campaign_start_gate",
    "consumption_key_for_envelope",
    "load_campaign_plan",
    "load_trust_registry",
]
