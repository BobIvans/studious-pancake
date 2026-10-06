"""Governed one-shot native capture. No subscriptions or execution authority.

Every physical request uses the existing Transport and ProviderGovernance.
Discovery is only a hint; pool/config/vault/mint/oracle/program accounts must be
re-read in one finalized RPC bank before publishing any shadow quote.
"""

from __future__ import annotations

from dataclasses import asdict
import copy
import time
from typing import Any, Callable
from uuid import uuid4

from src.direct_venue.cpmm_math import RAYDIUM_FEE_SOURCE_REVISION
from src.providers.raydium_cpmm_native import (
    CLOCK,
    SCHEMA,
    NativeAccount,
    NativeCaptureError,
    canonical_json,
    content_hash,
    decode_native_capture,
    integer,
    key,
    pool_pointers,
    program_data_address,
)
from src.provider_governance import (
    AdmissionRequest,
    ProviderEntitlement,
    ProviderGovernance,
    ProviderOperation,
)
from src.routing.transport import HttpxJsonTransport
from src.strategy.exact_cpmm_capacity import (
    MAINNET_GENESIS,
    PINNED_DECODER_REVISION,
    RAYDIUM_CPMM_PROGRAM_ID,
)
from .discovery import DiscoveryRequest, PublicMarketDiscovery
from .source_catalog import load_market_source_catalog
from .streams import RawStreamEvent, RecoverableStreamJournal

from src.qualification_campaign.profiles import public_rpc_profile, READ_RPC_METHODS

RPC_URL = public_rpc_profile().endpoint
DISCOVERY_URL = "https://api-v3.raydium.io/pools/info/list"
RPC_PROVIDER = "solana_rpc"
DISCOVERY_PROVIDER = "raydium-native-discovery"
SOURCE = "raydium-native-cpmm"
ANONYMOUS_REF = "anonymous-public-read"
ANONYMOUS_GENERATION = "anonymous-v1"
RPC_METHODS = READ_RPC_METHODS


def public_read_entitlements(
    *, expires_at_epoch_seconds: int
) -> dict[str, ProviderEntitlement]:
    """Bounded public read scope; contains no credential value or live grants."""
    common: dict[str, Any] = {
        "generation": "native-cpmm-public-read-v1",
        "allowed_operations": frozenset(
            {ProviderOperation.DISCOVERY, ProviderOperation.BACKFILL}
        ),
        "window_seconds": 60,
        "request_limit": 8,
        "cost_unit_limit": 8,
        "spend_limit_micros": 0,
        "max_concurrency": 1,
        "expires_at_epoch_seconds": expires_at_epoch_seconds,
        "quota_pool_ref": "native-cpmm-public-reads-v1",
        "credential_ref": ANONYMOUS_REF,
        "credential_generation": ANONYMOUS_GENERATION,
    }
    rpc = ProviderEntitlement(
        provider_id=RPC_PROVIDER,
        **common,
        source_ref="https://solana.com/docs/references/clusters",
        allowed_endpoints=(RPC_URL,),
        allowed_http_methods=frozenset({"POST"}),
        allowed_rpc_methods=RPC_METHODS,
    )
    discovery = ProviderEntitlement(
        provider_id=DISCOVERY_PROVIDER,
        **common,
        source_ref="https://docs.raydium.io/raydium/for-developers/api",
        allowed_endpoints=(DISCOVERY_URL,),
        allowed_http_methods=frozenset({"GET"}),
        allowed_query_parameters=frozenset(
            {"poolType", "poolSortField", "sortType", "pageSize", "page"}
        ),
    )
    return {rpc.provider_id: rpc, discovery.provider_id: discovery}


def partition_for(pool_ids: tuple[str, ...]) -> str:
    if not 1 <= len(pool_ids) <= 8 or len(set(pool_ids)) != len(pool_ids):
        raise NativeCaptureError("require 1..8 unique pool addresses")
    return content_hash(tuple(sorted(key(p) for p in pool_ids)))


class GovernedNativeCpmmCollector:
    def __init__(
        self,
        governance: ProviderGovernance,
        transport: HttpxJsonTransport,
        *,
        wall_ns: Callable[[], int] = time.time_ns,
        profile=None,
        snapshot_provider=None,
        evidence_store=None,
        auth_headers=None,
    ) -> None:
        self.profile = profile or public_rpc_profile()
        self.snapshot_provider = snapshot_provider
        self.evidence_store = evidence_store
        self.auth_headers = auth_headers
        self.governance = governance
        self.transport = transport
        self.wall_ns = wall_ns
        self.receipts: list[dict[str, Any]] = []
        self.discovery: dict[str, Any] | None = None
        self._run_id = uuid4().hex
        self._sequence = 0
        self._deadline = governance.clock() + 45
        governance.bind_transport(transport)

    async def _physical(
        self,
        provider: str,
        operation: ProviderOperation,
        fingerprint: str,
        call: Callable,
    ) -> Any:
        manifest = self.governance.entitlement(provider)
        if manifest.credential_ref != (
            self.profile.credential_ref
            if provider == self.profile.profile_id
            else ANONYMOUS_REF
        ) or manifest.credential_generation != (
            self.profile.credential_generation
            if provider == self.profile.profile_id
            else ANONYMOUS_GENERATION
        ):
            raise NativeCaptureError(
                "collector credential scope differs from reviewed profile"
            )
        self._sequence += 1
        if self._sequence > self.profile.request_limit:
            raise NativeCaptureError("one-shot logical request budget exhausted")
        request = AdmissionRequest(
            work_id=f"native-capture:{self._run_id}:{self._sequence}",
            provider_id=provider,
            operation=operation,
            request_fingerprint=fingerprint,
            fairness_key="native-shadow-capture",
            deadline_at=self._deadline,
            expected_generation=manifest.generation,
        )
        return await self.governance.execute_physical(
            request,
            call,
            credential_ref=manifest.credential_ref,
            credential_generation=manifest.credential_generation,
        )

    async def discover(self, *, max_pools: int = 8) -> tuple[str, ...]:
        integer(max_pools, "pool discovery cap", 1)
        if max_pools > 8:
            raise NativeCaptureError("discovery pool cap exceeds eight")
        request = DiscoveryRequest(
            "raydium", required_program_id=RAYDIUM_CPMM_PROGRAM_ID
        )
        discovery = PublicMarketDiscovery(self.transport, load_market_source_catalog())
        result = await self._physical(
            DISCOVERY_PROVIDER,
            ProviderOperation.DISCOVERY,
            content_hash(asdict(request)),
            lambda: discovery.collect(
                (request,), observed_at=self.wall_ns() / 10**9, max_markets=512
            ),
        )
        self.discovery = asdict(result)
        if any(r.error for r in result.receipts) or not result.markets:
            raise NativeCaptureError(
                "public discovery unavailable or no CPMM metadata on bounded page"
            )
        # Selection is deterministic; metadata never supplies reserves or prices.
        return tuple(sorted({m.market_id for m in result.markets}))[:max_pools]

    async def _rpc(self, method: str, params: list[Any]) -> dict[str, Any]:
        if method not in READ_RPC_METHODS:
            raise NativeCaptureError("RPC method outside native read scope")
        body = {
            "jsonrpc": "2.0",
            "id": self._sequence + 1,
            "method": method,
            "params": params,
        }
        fingerprint = content_hash({"url": self.profile.endpoint, "body": body})
        started = self.wall_ns()
        receipt: dict[str, Any] = {
            "endpoint": self.profile.endpoint,
            "provider_id": self.profile.profile_id,
            "provider": self.profile.provider,
            "operator": self.profile.operator,
            "correlation_group": self.profile.correlation_group,
            "source_generation": self.profile.generation,
            "method": method,
            "request_id": body["id"],
            "request_body": body,
            "request_fingerprint": fingerprint,
            "requested_at_ns": started,
            "hash_kind": "canonical-json-sha256",
        }
        try:
            if self.evidence_store is not None:
                self.evidence_store.claim_attempt(self.profile)
            status, response_headers, response = await self._physical(
                self.profile.profile_id,
                ProviderOperation.BACKFILL,
                fingerprint,
                lambda: self.transport.request(
                    "POST",
                    self.profile.endpoint,
                    json_body=body,
                    headers=self.auth_headers,
                ),
            )
            receipt.update(
                http_status=status,
                available_at_ns=self.wall_ns(),
                response_hash=content_hash(response),
                raw_response=response,
                retry_after=response_headers.get("retry-after"),
                quality_state=(
                    "rate-limited"
                    if status == 429
                    else (
                        "unauthorized"
                        if status in (401, 403)
                        else "accepted" if status == 200 else "http-error"
                    )
                ),
            )
            if status != 200:
                raise NativeCaptureError("native RPC HTTP failure")
            if (
                not isinstance(response, dict)
                or response.get("jsonrpc") != "2.0"
                or response.get("id") != body["id"]
                or "error" in response
                or "result" not in response
            ):
                raise NativeCaptureError("native RPC schema/error response")
            self.receipts.append(receipt)
            return response
        except BaseException as exc:
            receipt.update(available_at_ns=self.wall_ns(), error=type(exc).__name__)
            receipt.setdefault(
                "quality_state",
                (
                    "timeout"
                    if "Timeout" in type(exc).__name__
                    else (
                        "cancelled"
                        if "Cancel" in type(exc).__name__
                        else "transport-or-schema-error"
                    )
                ),
            )
            if not self.receipts or self.receipts[-1] is not receipt:
                self.receipts.append(receipt)
            raise
        finally:
            if self.evidence_store is not None:
                self.evidence_store.append(
                    self.profile.profile_id,
                    {"kind": "rpc_observation", **receipt},
                    observed_at_ns=started,
                    available_at_ns=receipt["available_at_ns"],
                )

    @staticmethod
    def _accounts(
        addresses: tuple[str, ...], response: dict[str, Any], *, minimum_slot: int = 1
    ) -> tuple[int, dict[str, NativeAccount]]:
        result = response.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("context"), dict):
            raise NativeCaptureError("account context missing")
        slot = integer(
            result["context"].get("slot"), "account context slot", minimum_slot
        )
        values = result.get("value")
        if not isinstance(values, list) or len(values) != len(addresses):
            raise NativeCaptureError("account set missing or wrong cardinality")
        return slot, {
            a: NativeAccount.from_rpc(a, v)
            for a, v in zip(addresses, values, strict=True)
        }

    async def collect(self, pool_ids: tuple[str, ...]) -> dict[str, Any]:
        if self.snapshot_provider is not None:
            return await self.snapshot_provider.collect(pool_ids)
        partition_for(pool_ids)
        pools = tuple(sorted(pool_ids))
        genesis = await self._rpc("getGenesisHash", [])
        if genesis["result"] != MAINNET_GENESIS:
            raise NativeCaptureError("public RPC genesis mismatch")
        preflight_addresses = (*pools, RAYDIUM_CPMM_PROGRAM_ID)
        preflight = await self._rpc(
            "getMultipleAccounts",
            [
                list(preflight_addresses),
                {"encoding": "base64", "commitment": "finalized"},
            ],
        )
        first_slot, initial = self._accounts(preflight_addresses, preflight)
        pointers = {p: pool_pointers(initial[p]) for p in pools}
        programdata = program_data_address(initial[RAYDIUM_CPMM_PROGRAM_ID])
        addresses = tuple(
            sorted(
                {
                    RAYDIUM_CPMM_PROGRAM_ID,
                    programdata,
                    CLOCK,
                    *(a for p in pointers.values() for a in p.required_accounts),
                }
            )
        )
        if len(addresses) > 100:
            raise NativeCaptureError("coherent account set exceeds RPC bound")
        response = await self._rpc(
            "getMultipleAccounts",
            [
                list(addresses),
                {
                    "encoding": "base64",
                    "commitment": "finalized",
                    "minContextSlot": first_slot,
                },
            ],
        )
        slot, coherent = self._accounts(addresses, response, minimum_slot=first_slot)
        observed = self.receipts[-1]["available_at_ns"]
        if program_data_address(
            coherent[RAYDIUM_CPMM_PROGRAM_ID]
        ) != programdata or any(
            pool_pointers(coherent[p]) != pointers[p] for p in pools
        ):
            raise NativeCaptureError(
                "account pointers changed during capture; full repair required"
            )
        block_response = await self._rpc(
            "getBlock",
            [
                slot,
                {
                    "commitment": "finalized",
                    "transactionDetails": "none",
                    "rewards": False,
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        )
        metadata = copy.deepcopy(response)
        values = metadata["result"].pop("value")
        payload = {
            "schema": SCHEMA,
            "decoder_revision": PINNED_DECODER_REVISION,
            "source_revision": RAYDIUM_FEE_SOURCE_REVISION,
            "evidence_kind": "captured-rpc",
            "genesis_hash": genesis["result"],
            "commitment": "finalized",
            "slot": slot,
            "pool_ids": list(pools),
            "observed_at_ns": observed,
            "available_at_ns": self.wall_ns(),
            "block": block_response["result"],
            "accounts": [
                {"address": a, "value": v}
                for a, v in zip(addresses, values, strict=True)
            ],
            "account_response_metadata": metadata,
            "account_response_hash": content_hash(response),
            "manifest_sha256": self.governance.entitlement(
                self.profile.profile_id
            ).manifest_sha256,
            "rpc_receipts": [
                {k: v for k, v in r.items() if k != "raw_response"}
                for r in self.receipts
            ],
            "rpc_profile_generation": self.profile.generation,
            "rpc_quorum": {"accepted": False, "reason": "BLOCKED_SINGLE_SOURCE"},
        }
        decode_native_capture(payload)
        return payload

    async def collect_into(
        self, journal: RecoverableStreamJournal, pool_ids: tuple[str, ...]
    ) -> dict[str, Any]:
        """Persist full evidence or an availability barrier, including cancellation."""
        partition = partition_for(pool_ids)
        try:
            payload = await self.collect(pool_ids)
            persist_capture(journal, payload)
            return payload
        except BaseException as exc:
            journal.block(
                source=SOURCE,
                partition=partition,
                available_at_ns=self.wall_ns(),
                reason=type(exc).__name__,
            )
            raise


def persist_capture(
    journal: RecoverableStreamJournal, payload: dict[str, Any], *, generation: int = 1
) -> RawStreamEvent:
    capture = decode_native_capture(payload)
    partition = partition_for(tuple(payload["pool_ids"]))
    event = RawStreamEvent(
        source=SOURCE,
        partition=partition,
        generation=generation,
        cursor=capture.available_at_ns,
        available_at_ns=capture.available_at_ns,
        observed_at_ns=capture.observed_at_ns,
        market_id=partition,
        revision=PINNED_DECODER_REVISION,
        payload_json=canonical_json(payload),
        block_hash=capture.block_hash,
        parent_hash=capture.parent_hash,
    )
    events = tuple(
        e
        for e in journal.events(available_at_ns=event.available_at_ns)
        if e.source == SOURCE and e.partition == partition
    )
    if events:
        previous = events[-1]
        old = decode_native_capture(json_load(previous.payload_json))
        if capture.slot < old.slot or (
            capture.slot == old.slot and capture.block_hash != old.block_hash
        ):
            journal.block(
                source=SOURCE,
                partition=partition,
                available_at_ns=event.available_at_ns,
                reason="finalized-bank-regression-or-conflict",
            )
            raise NativeCaptureError("finalized bank regressed or conflicted")
    journal.append(event)
    return event


def json_load(payload: str) -> dict[str, Any]:
    import json

    value = json.loads(payload)
    if not isinstance(value, dict):
        raise NativeCaptureError("native capture must be a mapping")
    return value
