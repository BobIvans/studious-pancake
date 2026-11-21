"""R13 Aftermath offline-to-governed quote ingress (PR #667 vertical slice).

The offline normalizer (:mod:`src.gpr_sui_shadow.providers.aftermath`, PR
#661) validates a ``POST /api/router/trade-route`` response into kernel
``NormalizedProviderQuote`` evidence but ships no ingress: nothing wires a
normalized batch into the frozen R13 quote/build kernel race, and no state
evidence can be attached to a quote. This module is that missing glue, and
nothing more:

- **offline path**: a retained (fixture/capture) payload is normalized by the
  existing adapter, optionally bound to independently captured Sui checkpoint
  evidence, and raced through the existing kernel (``QuoteRaceResult.build``);
  the R13 ``PoolIdentityDeduplicator`` correlation rules stay in the kernel —
  nothing is deduplicated twice.
- **live path**: gate-checked FIRST against the existing verdicts. The
  Aftermath live-capture gate (:func:`aftermath_live_capture_verdict`) and the
  GPR-03 Sui provider binding gate (:func:`live_binding_verdict`) must both
  return an authorized PASS before any transport is invoked; neither can pass
  in this slice, so every live attempt is a typed ``LIVE_READ_NOT_AUTHORIZED``
  refusal carrying the exact gate reasons. No environment variable,
  credential, configuration or fixture can flip a gate.

State evidence is never synthesized: a trade-route response carries no
checkpoint, so ``QuoteFreshness.checkpoint_sequence`` is set ONLY from a
caller-supplied :class:`AftermathStateEvidence` whose provenance comes from an
independently proven offline provider pair (see
``CheckpointConsistencyEvidence`` / ``OfflinePairVerdict`` in
``src/gpr_sui_shadow/providers``). Without it the checkpoint stays ``None``
(UNKNOWN is never zero) and a typed blocker is recorded.

Quote is not build: nothing here composes a PTB, signs, sends, borrows, or
enables a provider. NAVI lender qualification is owned by DAG N09 /
R02-CAP-C and is untouched. This module imports no network libraries.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from ..models import sha, uint
from . import LIVE_SUI_PROVIDERS_BLOCKED, live_binding_verdict
from .aftermath import (
    AFTERMATH_EVIDENCE_STATE,
    AFTERMATH_LIVE_CAPTURE_BLOCKED,
    AftermathLiveCaptureVerdict,
    AftermathQuoteBatch,
    AftermathSwapRouteRequest,
    AftermathTransport,
    aftermath_live_capture_verdict,
    build_kernel_race_request,
    kernel_race_inputs,
    normalize_aftermath_trade_route_response,
    normalize_via_transport,
)
from src.execution.quote_build_kernel import (
    NormalizedProviderQuote,
    QuoteRaceResult,
)

__all__ = [
    "AFTERMATH_INGRESS_EVIDENCE_STATE",
    "AFTERMATH_INGRESS_VERSION",
    "AFTERMATH_LANE_STAGE_STATUSES",
    "AFTERMATH_STATE_EVIDENCE_ATTACHED_FROM_INDEPENDENT_CAPTURE",
    "AFTERMATH_STATE_EVIDENCE_REQUIRED",
    "AFTERMATH_STATE_EVIDENCE_UNATTACHED",
    "AFTERMATH_SUI_PROVIDER_QUORUM_REQUIRED",
    "AftermathIngressError",
    "AftermathIngressFailureCode",
    "AftermathIngressResult",
    "AftermathLaneStageStatus",
    "AftermathLiveReadGateVerdict",
    "AftermathStateEvidence",
    "ingest_offline_payload",
    "ingest_via_transport",
    "live_read_gate_verdict",
    "provider_lane_status",
]

# --------------------------------------------------------------------------
# Pinned identity constants
# --------------------------------------------------------------------------

AFTERMATH_INGRESS_VERSION = "r13.aftermath-ingress.v1"
#: Typed evidence state of the ingress outcome: quotes are comparable offline
#: evidence through the frozen kernel, never qualified execution input.
AFTERMATH_INGRESS_EVIDENCE_STATE = "INGRESS_OFFLINE_COMPARABLE_UNQUALIFIED"
#: State-binding labels (typed data, not exceptions).
AFTERMATH_STATE_EVIDENCE_UNATTACHED = "AFTERMATH_STATE_EVIDENCE_UNATTACHED"
AFTERMATH_STATE_EVIDENCE_ATTACHED_FROM_INDEPENDENT_CAPTURE = (
    "AFTERMATH_STATE_EVIDENCE_ATTACHED_FROM_INDEPENDENT_CAPTURE"
)
#: Blocker recorded when no independently captured state evidence is supplied.
AFTERMATH_STATE_EVIDENCE_REQUIRED = "AFTERMATH_STATE_EVIDENCE_REQUIRED"
#: Blocker/refusal component for a missing independent Sui provider pair.
AFTERMATH_SUI_PROVIDER_QUORUM_REQUIRED = "AFTERMATH_SUI_PROVIDER_QUORUM_REQUIRED"
#: The only gate status that permits a live read (no gate can emit it here).
AFTERMATH_INGRESS_GATE_PASS = "PASS"
AFTERMATH_INGRESS_GATE_BLOCKED = "BLOCKED"

#: Ladder statuses (typed data; deterministic, never inferred).
AFTERMATH_LANE_ACHIEVED = "ACHIEVED"
AFTERMATH_LANE_BLOCKED = "BLOCKED"
AFTERMATH_LANE_NOT_STARTED = "NOT_STARTED"

_MAX_IDENTITY_TEXT = 128


# --------------------------------------------------------------------------
# Typed ingress failures
# --------------------------------------------------------------------------


class AftermathIngressFailureCode(StrEnum):
    """Typed ingress refusal codes (adapter codes are never reused here)."""

    DISABLED = "disabled"
    LIVE_READ_NOT_AUTHORIZED = "live_read_not_authorized"
    STATE_EVIDENCE_INVALID = "state_evidence_invalid"


class AftermathIngressError(Exception):
    """Typed fail-closed ingress error (gate refusals, malformed evidence)."""

    def __init__(self, code: AftermathIngressFailureCode, detail: str) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code
        self.detail = detail


# --------------------------------------------------------------------------
# Independently captured state evidence (checkpoint provenance)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AftermathStateEvidence:
    """Checkpoint provenance from an independent Sui state capture.

    Every field is caller-supplied and validated; nothing is defaulted into
    existence. The intended source is a proven two-provider offline pair
    (``verify_offline_pair`` -> ``OfflinePairVerdict``): ``checkpoint_sequence``
    /``checkpoint_digest`` are the quorum-agreed checkpoint facts, the
    request/response hashes are the capture's raw payload provenance, and
    ``capture_provider``/``capture_correlation_group`` identify the state
    source (distinct from the Aftermath SOR group by construction).
    """

    checkpoint_sequence: int
    checkpoint_digest: str
    capture_provider: str
    capture_correlation_group: str
    capture_request_hash: str
    capture_response_hash: str
    captured_at_ns: int
    source_generation: str
    evidence_ref: str

    def __post_init__(self) -> None:
        try:
            uint(self.checkpoint_sequence, "checkpoint_sequence", 1)
            sha(self.checkpoint_digest)
            sha(self.capture_request_hash)
            sha(self.capture_response_hash)
            sha(self.evidence_ref)
            uint(self.captured_at_ns, "captured_at_ns", 1, 2**63 - 1)
        except ValueError as error:
            raise AftermathIngressError(
                AftermathIngressFailureCode.STATE_EVIDENCE_INVALID,
                str(error),
            ) from error
        for label, value in (
            ("capture_provider", self.capture_provider),
            ("capture_correlation_group", self.capture_correlation_group),
            ("source_generation", self.source_generation),
        ):
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value) > _MAX_IDENTITY_TEXT
            ):
                raise AftermathIngressError(
                    AftermathIngressFailureCode.STATE_EVIDENCE_INVALID,
                    f"{label} must be a non-empty bounded identity string",
                )
        for label, value in (
            ("capture_provider", self.capture_provider),
            ("capture_correlation_group", self.capture_correlation_group),
        ):
            if value != value.lower():
                raise AftermathIngressError(
                    AftermathIngressFailureCode.STATE_EVIDENCE_INVALID,
                    f"{label} must be a canonical lowercase identity",
                )


# --------------------------------------------------------------------------
# Live-read gate (existing verdicts consulted; never weakened)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AftermathLiveReadGateVerdict:
    """Typed conjunction of the existing live gates for one ingest attempt."""

    status: str
    reasons: tuple[str, ...]
    capture_verdict: AftermathLiveCaptureVerdict
    ingress_version: str


def live_read_gate_verdict(
    sui_provider_pair: tuple[Sequence[object], Sequence[object]] | None = None,
) -> AftermathLiveReadGateVerdict:
    """Evaluate the existing provider gates; PASS is currently unreachable.

    ``sui_provider_pair`` is the ``(bindings, evidences)`` pair consumed by
    :func:`src.gpr_sui_shadow.providers.live_binding_verdict`; an inconsistent
    pair raises its typed ``ValueError`` strings, which are preserved verbatim
    as gate reasons (never collapsed into a generic refusal).
    """
    capture = aftermath_live_capture_verdict()
    reasons: list[str] = []
    if capture.status != AFTERMATH_INGRESS_GATE_PASS:
        reasons.append(capture.reason)
    if sui_provider_pair is None:
        reasons.append(AFTERMATH_SUI_PROVIDER_QUORUM_REQUIRED)
    else:
        bindings, evidences = sui_provider_pair
        try:
            binding_verdict = live_binding_verdict(bindings, evidences)
        except ValueError as error:
            reasons.append(str(error))
        else:
            if binding_verdict.status != AFTERMATH_INGRESS_GATE_PASS:
                reasons.append(binding_verdict.reason)
    status = (
        AFTERMATH_INGRESS_GATE_PASS if not reasons else AFTERMATH_INGRESS_GATE_BLOCKED
    )
    return AftermathLiveReadGateVerdict(
        status=status,
        reasons=tuple(reasons),
        capture_verdict=capture,
        ingress_version=AFTERMATH_INGRESS_VERSION,
    )


# --------------------------------------------------------------------------
# Governed ingress outcome
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AftermathIngressResult:
    """Offline-to-governed outcome: batch + kernel race + state binding.

    ``race`` is the frozen kernel's own ``QuoteRaceResult`` (winner, typed
    loss reasons, preserved losers/failures) — the R13 pool dedup runs there
    and nowhere else. ``evidence_state`` of every entry stays the adapter's
    offline ``ADAPTER_BUILT_OFFLINE_UNQUALIFIED``; qualification is owned by
    the existing campaign/R06 gates, not by this ingress.
    """

    batch: AftermathQuoteBatch
    race: QuoteRaceResult
    state_binding: str
    state_evidence: AftermathStateEvidence | None
    blockers: tuple[str, ...]
    evidence_state: str = AFTERMATH_INGRESS_EVIDENCE_STATE


def _bind_state_evidence(
    batch: AftermathQuoteBatch, state_evidence: AftermathStateEvidence
) -> AftermathQuoteBatch:
    """Attach the proven checkpoint sequence to every normalized quote.

    The trade-route payload itself carries no checkpoint, so the attachment is
    a pure provenance join with independently captured state evidence; every
    other freshness field stays exactly as the adapter decoded it.
    """
    entries = tuple(
        replace(
            entry,
            normalized=replace(
                entry.normalized,
                freshness=replace(
                    entry.normalized.freshness,
                    checkpoint_sequence=state_evidence.checkpoint_sequence,
                ),
            ),
        )
        for entry in batch.entries
    )
    return replace(batch, entries=entries)


def _govern(
    batch: AftermathQuoteBatch,
    request: AftermathSwapRouteRequest,
    *,
    state_evidence: AftermathStateEvidence | None,
    competing_quotes: Sequence[NormalizedProviderQuote],
    now_ns: int,
) -> AftermathIngressResult:
    blockers: list[str] = []
    bound_batch = batch
    if state_evidence is None:
        blockers.append(AFTERMATH_STATE_EVIDENCE_REQUIRED)
    else:
        if not isinstance(state_evidence, AftermathStateEvidence):
            raise AftermathIngressError(
                AftermathIngressFailureCode.STATE_EVIDENCE_INVALID,
                "state_evidence must be an AftermathStateEvidence instance",
            )
        bound_batch = _bind_state_evidence(batch, state_evidence)
    for quote in competing_quotes:
        if not isinstance(quote, NormalizedProviderQuote):
            raise AftermathIngressError(
                AftermathIngressFailureCode.STATE_EVIDENCE_INVALID,
                "competing_quotes entries must be kernel NormalizedProviderQuote",
            )
    quotes, failures = kernel_race_inputs(bound_batch)
    race = QuoteRaceResult.build(
        request=build_kernel_race_request(request),
        quotes=tuple(competing_quotes) + tuple(quotes),
        failures=failures,
        now_ns=now_ns,
    )
    return AftermathIngressResult(
        batch=bound_batch,
        race=race,
        state_binding=(
            AFTERMATH_STATE_EVIDENCE_UNATTACHED
            if state_evidence is None
            else AFTERMATH_STATE_EVIDENCE_ATTACHED_FROM_INDEPENDENT_CAPTURE
        ),
        state_evidence=state_evidence,
        blockers=tuple(blockers),
    )


def ingest_offline_payload(
    payload: Mapping[str, object],
    *,
    request: AftermathSwapRouteRequest,
    received_at_ns: int,
    state_evidence: AftermathStateEvidence | None = None,
    competing_quotes: Sequence[NormalizedProviderQuote] = (),
    now_ns: int | None = None,
) -> AftermathIngressResult:
    """Normalize a retained payload and race it through the existing kernel.

    Deterministic offline path: same payload, request, ``received_at_ns`` and
    ``state_evidence`` produce byte-identical results (a fixed ``now_ns``
    defaults to ``received_at_ns`` so no replay synthesizes a clock). The
    state evidence is validated by construction; without it the checkpoint
    stays UNKNOWN and ``AFTERMATH_STATE_EVIDENCE_REQUIRED`` is recorded.
    """
    batch = normalize_aftermath_trade_route_response(
        payload, request=request, received_at_ns=received_at_ns
    )
    return _govern(
        batch,
        request,
        state_evidence=state_evidence,
        competing_quotes=competing_quotes,
        now_ns=received_at_ns if now_ns is None else now_ns,
    )


def ingest_via_transport(
    transport: AftermathTransport | None,
    request: AftermathSwapRouteRequest,
    *,
    received_at_ns: int,
    state_evidence: AftermathStateEvidence | None = None,
    competing_quotes: Sequence[NormalizedProviderQuote] = (),
    now_ns: int | None = None,
    sui_provider_pair: tuple[Sequence[object], Sequence[object]] | None = None,
) -> AftermathIngressResult:
    """Gate-checked transport ingest; every live attempt is refused today.

    The gate runs BEFORE the transport is ever invoked: the Aftermath
    live-capture verdict and the GPR-03 independent provider binding verdict
    must both be an authorized PASS. Neither can return PASS in this slice,
    so a supplied transport yields a typed ``LIVE_READ_NOT_AUTHORIZED``
    refusal carrying the exact gate reasons, and ``None`` stays a typed
    ``DISABLED`` refusal (offline use goes through
    :func:`ingest_offline_payload`).
    """
    if transport is None:
        raise AftermathIngressError(
            AftermathIngressFailureCode.DISABLED,
            "no transport is shipped with this ingress; live capture is not "
            f"authorized ({AFTERMATH_LIVE_CAPTURE_BLOCKED}) and offline use "
            "must call ingest_offline_payload",
        )
    gate = live_read_gate_verdict(sui_provider_pair)
    if gate.status != AFTERMATH_INGRESS_GATE_PASS:
        raise AftermathIngressError(
            AftermathIngressFailureCode.LIVE_READ_NOT_AUTHORIZED,
            "; ".join(gate.reasons),
        )
    batch = normalize_via_transport(transport, request, received_at_ns=received_at_ns)
    return _govern(
        batch,
        request,
        state_evidence=state_evidence,
        competing_quotes=competing_quotes,
        now_ns=received_at_ns if now_ns is None else now_ns,
    )


# --------------------------------------------------------------------------
# Provider status ladder (trigger deliverable; deterministic, typed)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AftermathLaneStageStatus:
    """One stage of the provider status ladder with its typed reason."""

    stage: str
    status: str
    reason: str


#: The deterministic ladder as of ``r13.aftermath-ingress.v1``. Reasons name
#: the owning gate/owner verbatim; nothing is inferred from mutable state.
AFTERMATH_LANE_STAGE_STATUSES: tuple[AftermathLaneStageStatus, ...] = (
    AftermathLaneStageStatus(
        stage="DOCUMENTED",
        status=AFTERMATH_LANE_ACHIEVED,
        reason="wave-1/wave-2 dossiers + AFTERMATH_ADAPTER_SCHEMA_PIN",
    ),
    AftermathLaneStageStatus(
        stage="ADAPTER",
        status=AFTERMATH_LANE_ACHIEVED,
        reason="r13.aftermath-adapter.v1 (PR #661 offline normalizer)",
    ),
    AftermathLaneStageStatus(
        stage="BOOT_WIRED",
        status=AFTERMATH_LANE_ACHIEVED,
        reason="r13.aftermath-ingress.v1 offline governed ingress (PR #667)",
    ),
    AftermathLaneStageStatus(
        stage="COMPARABLE",
        status=AFTERMATH_LANE_ACHIEVED,
        reason="kernel race comparable offline (exact amount/type binding)",
    ),
    AftermathLaneStageStatus(
        stage="LIVE_READ",
        status=AFTERMATH_LANE_BLOCKED,
        reason=(f"{AFTERMATH_LIVE_CAPTURE_BLOCKED}; {LIVE_SUI_PROVIDERS_BLOCKED}"),
    ),
    AftermathLaneStageStatus(
        stage="ROOTED",
        status=AFTERMATH_LANE_BLOCKED,
        reason=f"{LIVE_SUI_PROVIDERS_BLOCKED} (independent provider quorum)",
    ),
    AftermathLaneStageStatus(
        stage="BUILDABLE",
        status=AFTERMATH_LANE_NOT_STARTED,
        reason="R-03 builder owner; quote is not a PTB (add-trade separate)",
    ),
    AftermathLaneStageStatus(
        stage="R02_QUALIFIED",
        status=AFTERMATH_LANE_BLOCKED,
        reason="no qualified capital evidence; NAVI qualification owned by DAG N09 (R02-CAP-C)",
    ),
    AftermathLaneStageStatus(
        stage="R05_SIMULATED",
        status=AFTERMATH_LANE_NOT_STARTED,
        reason="R05 exact simulation owner",
    ),
    AftermathLaneStageStatus(
        stage="R06_PAPER_QUALIFIED",
        status=AFTERMATH_LANE_BLOCKED,
        reason="only the canonical R06/QPR paper service can promote",
    ),
)


def provider_lane_status() -> tuple[AftermathLaneStageStatus, ...]:
    """Deterministic provider status ladder (evidence receipts, not claims)."""
    return AFTERMATH_LANE_STAGE_STATUSES
