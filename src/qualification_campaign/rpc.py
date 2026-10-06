"""Native collector injection backed by the canonical rooted quorum gate."""

import asyncio
from dataclasses import asdict
import time
from typing import Protocol

from src.data_plane.common import CommitmentLevel
from src.data_plane.rpc import (
    RootedRpcQuorumGate,
    RootedRpcQuorumPolicy,
    RpcSample,
    RpcEndpointIdentity,
    RootedRpcSample,
)
from src.providers.raydium_cpmm_native import NativeCaptureError
from src.routing.transport import SanitizedTransportError
from src.strategy.exact_cpmm_capacity import MAINNET_GENESIS
from .identity import digest
import httpx


class RootedSnapshotProvider(Protocol):
    async def collect(self, pool_ids: tuple[str, ...]) -> dict: ...


class NativeRootedSnapshotProvider:
    """Preserve every provider's raw evidence, including failed members.

    Same finalized bank, exact account bytes and block identity must agree. Even
    agreeing public smoke sources cannot grant qualification authority.
    """

    def __init__(
        self, collectors, evidence_store, *, monotonic_ms=None, wall_ns=time.time_ns
    ):
        if not collectors or len(collectors) > 4:
            raise ValueError("require 1..4 RPC profiles")
        if len({c.profile.profile_id for c in collectors}) != len(collectors):
            raise ValueError("duplicate RPC profile")
        self.collectors = tuple(collectors)
        self.evidence = evidence_store
        self.monotonic_ms = monotonic_ms or (lambda: time.monotonic_ns() // 1_000_000)
        self.wall_ns = wall_ns
        self.last_bundle = None

    async def collect(self, pool_ids):
        capture_refs = []
        samples = []
        captures = []
        failures = []
        request_hash = digest({"pools": sorted(pool_ids), "commitment": "finalized"})
        for collector in self.collectors:
            profile = collector.profile
            start = self.monotonic_ms()
            try:
                capture = await collector.collect(pool_ids)
                observed = self.monotonic_ms()
                version = (await collector._rpc("getVersion", []))["result"]
                current = (
                    await collector._rpc("getSlot", [{"commitment": "processed"}])
                )["result"]
                root = (await collector._rpc("getSlot", [{"commitment": "finalized"}]))[
                    "result"
                ]
                state_hash = digest(
                    {
                        k: capture[k]
                        for k in (
                            "genesis_hash",
                            "commitment",
                            "slot",
                            "accounts",
                            "block",
                        )
                    }
                )
                sample = RpcSample(
                    profile.profile_id,
                    capture["genesis_hash"],
                    "getMultipleAccounts",
                    request_hash,
                    capture["slot"],
                    CommitmentLevel.FINALIZED,
                    state_hash,
                    capture["observed_at_ns"] // 1_000_000,
                    observed,
                    self.monotonic_ms() - start,
                )
                identity = RpcEndpointIdentity(
                    profile.profile_id,
                    profile.provider.lower(),
                    profile.operator.lower(),
                    profile.correlation_group.lower(),
                    "profile-unspecified",
                    profile.credential_ref,
                    capture["genesis_hash"],
                    version["solana-core"],
                    version["feature-set"],
                    0,
                    capture["observed_at_ns"] // 1_000_000,
                    observed,
                    observed + 45_000,
                )
                samples.append(
                    RootedRpcSample(
                        sample,
                        identity,
                        current,
                        root,
                        root,
                        capture["block"]["blockhash"],
                    )
                )
                captures.append(capture)
                capture_refs.append(
                    self.evidence.append(
                        profile.profile_id,
                        {"kind": "native_capture", "payload": capture},
                        observed_at_ns=capture["observed_at_ns"],
                        available_at_ns=self.wall_ns(),
                    )
                )
            except asyncio.CancelledError:
                self.evidence.append(
                    profile.profile_id,
                    {
                        "kind": "cancelled_capture",
                        "source_generation": profile.generation,
                    },
                    observed_at_ns=self.wall_ns(),
                )
                raise
            except (
                NativeCaptureError,
                ValueError,
                KeyError,
                TypeError,
                RuntimeError,
                OSError,
                httpx.TransportError,
            ) as exc:
                failures.append(
                    {
                        "provider_id": profile.profile_id,
                        "source_generation": profile.generation,
                        "error": type(exc).__name__,
                    }
                )
                if isinstance(exc, (NativeCaptureError, SanitizedTransportError)):
                    failures[-1]["failure_reason"] = str(exc)
                self.evidence.append(
                    profile.profile_id,
                    {"kind": "capture_failure", **failures[-1]},
                    observed_at_ns=self.wall_ns(),
                )
        gate = RootedRpcQuorumGate(
            RootedRpcQuorumPolicy(max_observation_age_ms=45_000, max_root_lag_slots=128)
        )
        evaluated_wall_ms = self.wall_ns() // 1_000_000
        evaluated_monotonic_ms = self.monotonic_ms()
        decision = gate.evaluate(
            samples,
            expected_genesis_hash=MAINNET_GENESIS,
            expected_method="getMultipleAccounts",
            expected_request_hash=request_hash,
            min_context_slot=1,
            now_wall_ms=evaluated_wall_ms,
            now_monotonic_ms=evaluated_monotonic_ms,
        )
        result = asdict(decision)
        result["reason"] = decision.reason.value
        if len(self.collectors) == 1:
            result.update(accepted=False, reason="BLOCKED_SINGLE_SOURCE")
        elif failures:
            result.update(accepted=False, reason="BLOCKED_PROVIDER_FAILURE")
        elif len({c["slot"] for c in captures}) != 1:
            result.update(accepted=False, reason="BLOCKED_CONTEXT_SLOT_DISAGREEMENT")
        elif any(c.profile.smoke_only for c in self.collectors):
            result.update(accepted=False, reason="BLOCKED_PUBLIC_SMOKE_SOURCE")
        result["canonical_gate_evidence_hash"] = result.pop("evidence_hash")
        result["evidence_hash"] = digest(result)
        bundle = {
            "kind": "rooted_snapshot_bundle",
            "request_hash": request_hash,
            "capture_refs": capture_refs,
            "failures": failures,
            "quorum": result,
            "rooted_samples": [asdict(s) for s in samples],
            "quorum_policy": asdict(gate.policy),
            "evaluated_at_wall_ms": evaluated_wall_ms,
            "evaluated_at_monotonic_ms": evaluated_monotonic_ms,
        }
        # Enums are strings; the journal stores the entire replayable decision input.
        self.evidence.append("rpc-quorum", bundle, observed_at_ns=self.wall_ns())
        self.last_bundle = bundle
        if not captures:
            raise NativeCaptureError(
                "no usable native capture; negative evidence retained"
            )
        canonical_id = decision.canonical_endpoint_id
        index = next(
            (i for i, s in enumerate(samples) if s.sample.endpoint_id == canonical_id),
            0,
        )
        payload = dict(captures[index])
        payload["rpc_quorum"] = result
        payload["campaign_manifest_hash"] = self.evidence.manifest.campaign_id
        return payload


def validate_quorum_evidence(bundle, evidence):
    """A replayed flag cannot replace the canonical gate and exact raw state."""
    samples = []
    for raw in bundle["rooted_samples"]:
        item = dict(raw)
        sample_data = dict(item.pop("sample"))
        identity = item.pop("identity")
        sample_data["commitment"] = CommitmentLevel(sample_data["commitment"])
        samples.append(
            RootedRpcSample(
                RpcSample(**sample_data), RpcEndpointIdentity(**identity), **item
            )
        )
    policy = dict(bundle["quorum_policy"])
    policy["required_commitment"] = CommitmentLevel(policy["required_commitment"])
    decision = RootedRpcQuorumGate(RootedRpcQuorumPolicy(**policy)).evaluate(
        samples,
        expected_genesis_hash=MAINNET_GENESIS,
        expected_method="getMultipleAccounts",
        expected_request_hash=bundle["request_hash"],
        min_context_slot=1,
        now_wall_ms=bundle["evaluated_at_wall_ms"],
        now_monotonic_ms=bundle["evaluated_at_monotonic_ms"],
    )
    result = dict(bundle["quorum"])
    recorded = result.pop("evidence_hash")
    if (
        digest(result) != recorded
        or decision.evidence_hash != result["canonical_gate_evidence_hash"]
    ):
        raise ValueError("QUORUM_DECISION_HASH_MISMATCH")
    if result["accepted"] and (not decision.accepted or bundle.get("failures")):
        raise ValueError("QUORUM_DECISION_MISMATCH")
    by_id = {
        e.identity: evidence.expand(e.payload_json)
        for e in evidence.journal.events(available_at_ns=2**63 - 1)
    }
    captures = [by_id[r]["payload"] for r in bundle["capture_refs"]]
    if result["accepted"] and (
        len({c["slot"] for c in captures}) != 1 or len(captures) != len(samples)
    ):
        raise ValueError("QUORUM_CAPTURE_MISMATCH")
    for sample, capture in zip(samples, captures, strict=True):
        state_hash = digest(
            {
                k: capture[k]
                for k in ("genesis_hash", "commitment", "slot", "accounts", "block")
            }
        )
        if (
            state_hash != sample.sample.payload_hash
            or capture["evidence_kind"] != "captured-rpc"
        ):
            raise ValueError("QUORUM_RAW_STATE_MISMATCH")
    result["evidence_hash"] = recorded
    return result
