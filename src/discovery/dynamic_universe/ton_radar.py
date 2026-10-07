"""Bounded TON research ingestion; this module has no execution dependencies.

REST and RFQ payloads are candidate evidence only. A syntactically valid TON
address is not a proven jetton identity, and none of these records can be used
as a local atomic flash-capital edge.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Protocol

from src.routing.transport import SanitizedTransportError, Transport

TON_EXECUTION_CLASS = "TON_ASYNC_MULTI_CONTRACT"
_ENDPOINTS = ("assets", "pools", "stats")


class TonSchemaError(ValueError):
    """Public, non-secret reason for refusing an entire provider batch."""


def canonical_ton_address(value: Any) -> str:
    """Normalize raw/friendly mainnet addresses, verifying friendly CRC16.

    Address syntax does not establish chain existence, code or jetton semantics.
    Test-only friendly addresses are refused by this mainnet research adapter.
    """
    if not isinstance(value, str):
        raise TonSchemaError("missing TON address")
    if re.fullmatch(r"(?:0|-1):[0-9a-fA-F]{64}", value):
        raw_workchain, account = value.split(":")
        return f"{raw_workchain}:{account.lower()}"
    if not re.fullmatch(r"[A-Za-z0-9_+/=-]{48}", value):
        raise TonSchemaError("invalid TON address")
    try:
        decoded = base64.b64decode(value, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error):
        raise TonSchemaError("invalid friendly TON address") from None
    if len(decoded) != 36 or decoded[0] not in (0x11, 0x51):
        raise TonSchemaError("unsupported TON address network or tag")
    if binascii.crc_hqx(decoded[:34], 0).to_bytes(2, "big") != decoded[34:]:
        raise TonSchemaError("invalid TON address checksum")
    workchain = int.from_bytes(decoded[1:2], "big", signed=True)
    if workchain not in (0, -1):
        raise TonSchemaError("unsupported TON workchain")
    return f"{workchain}:{decoded[2:34].hex()}"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TonDiscoveryEnvelope:
    """Immutable provider payload and normalized records for offline replay."""

    source: str
    source_url: str
    resource: str
    observed_at: str
    campaign_generation: str
    request_hash: str
    response_hash: str
    payload_json: str
    records_json: str
    negative_evidence: tuple[str, ...] = ()
    status_code: int | None = None
    retry_after: str | None = None
    execution_class: str = TON_EXECUTION_CLASS
    verification_state: str = "DISCOVERY_ONLY"
    executable: bool = False

    def __post_init__(self) -> None:
        if (
            self.execution_class != TON_EXECUTION_CLASS
            or self.verification_state != "DISCOVERY_ONLY"
            or self.executable is not False
        ):
            raise ValueError("TON radar envelopes are permanently research-only")
        if _hash(self.payload_json) != self.response_hash:
            raise ValueError("TON replay payload hash mismatch")
        records = json.loads(self.records_json)
        if not isinstance(records, list) or any(
            not isinstance(record, dict)
            or record.get("chain") != "ton"
            or record.get("execution_class") != TON_EXECUTION_CLASS
            or record.get("verification_state") != "DISCOVERY_ONLY"
            or record.get("executable") is not False
            or record.get("identifier_verified") is not False
            or record.get("state_verified") is not False
            for record in records
        ):
            raise ValueError("TON replay records must remain research-only")
        if self.negative_evidence and records:
            raise ValueError("negative TON evidence cannot contain candidates")

    @property
    def records(self) -> tuple[dict[str, Any], ...]:
        # Return independent copies; mutating a consumer record cannot alter replay.
        return tuple(json.loads(self.records_json))

    def to_dict(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TonDiscoveryEnvelope:
        fields = dict(value)
        fields["negative_evidence"] = tuple(fields.get("negative_evidence", ()))
        return cls(**fields)


class OmnistonReader(Protocol):
    async def discover_routes(
        self, markets: Sequence[Mapping[str, Any]], *, max_routes: int
    ) -> Mapping[str, Any]:
        """Return read-only {routes: [{pool_addresses, input_asset, output_asset}]}.

        Implementations must request quotes/evidence only; transaction creation,
        signing, message sending and settlement are outside this interface.
        """
        ...


def _research_record(kind: str, **fields: Any) -> dict[str, Any]:
    return {
        **fields,
        "kind": kind,
        "chain": "ton",
        "execution_class": TON_EXECUTION_CLASS,
        "verification_state": "DISCOVERY_ONLY",
        "identifier_verified": False,
        "state_verified": False,
        "executable": False,
    }


def _rows(payload: Any, key: str, maximum: int) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        raise TonSchemaError(f"missing {key} array")
    rows = payload[key]
    if len(rows) > maximum:
        raise TonSchemaError("provider record budget exceeded")
    if any(not isinstance(row, dict) for row in rows):
        raise TonSchemaError("provider row is not an object")
    return rows


def _deduplicate(records: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        identifier = record["record_id"]
        if identifier in unique and unique[identifier] != record:
            raise TonSchemaError("duplicate TON identity disagrees")
        unique[identifier] = record
    return tuple(unique[key] for key in sorted(unique))


def normalize_ston_payload(
    resource: str, payload: Any, *, max_records: int = 50_000
) -> tuple[dict[str, Any], ...]:
    """Reject schema drift/conflicting duplicates without emitting partial rows."""
    records: list[dict[str, Any]] = []
    if resource == "assets":
        for row in _rows(payload, "asset_list", max_records):
            address = canonical_ton_address(row.get("contract_address"))
            metadata = row.get("meta")
            if metadata is None:
                metadata = {}
            if not isinstance(metadata, dict):
                raise TonSchemaError("asset metadata is not an object")
            symbol = metadata.get("symbol", row.get("symbol", ""))
            if not isinstance(symbol, str):
                raise TonSchemaError("asset symbol is not display text")
            records.append(
                _research_record(
                    "asset",
                    record_id=f"ton:asset:{address}",
                    canonical_identifier=address,
                    symbol=symbol,
                    # Provider metadata is deliberately not on-chain decimals.
                    provider_metadata=metadata,
                )
            )
    elif resource == "pools":
        for row in _rows(payload, "pool_list", max_records):
            address = canonical_ton_address(row.get("address"))
            token0 = canonical_ton_address(row.get("token0_address"))
            token1 = canonical_ton_address(row.get("token1_address"))
            if token0 == token1:
                raise TonSchemaError("pool has identical asset addresses")
            records.append(
                _research_record(
                    "market",
                    record_id=f"ton:ston:{address}",
                    market_id=address,
                    venue="ston.fi",
                    asset_a=token0,
                    asset_b=token1,
                    underlying_resources=[f"ton:pool:{address}"],
                    correlation_group=f"ton:pool:{address}",
                )
            )
    elif resource == "stats":
        if not isinstance(payload, dict) or not isinstance(payload.get("stats"), dict):
            raise TonSchemaError("missing stats object")
        if not payload["stats"]:
            raise TonSchemaError("empty stats object")
        records.append(
            _research_record(
                "stats", record_id="ton:ston:stats", provider_stats=payload["stats"]
            )
        )
    elif resource == "routes":
        for row in _rows(payload, "routes", max_records):
            pools = row.get("pool_addresses")
            if not isinstance(pools, list) or not pools or len(pools) > 5:
                raise TonSchemaError("route lacks bounded underlying pool identities")
            normalized_pools = tuple(canonical_ton_address(pool) for pool in pools)
            if len(set(normalized_pools)) != len(normalized_pools):
                raise TonSchemaError("route repeats underlying liquidity")
            token0 = canonical_ton_address(row.get("input_asset"))
            token1 = canonical_ton_address(row.get("output_asset"))
            if token0 == token1:
                raise TonSchemaError("route has identical asset addresses")
            resources = [f"ton:pool:{pool}" for pool in normalized_pools]
            route_key = _hash(_canonical_json([token0, token1, resources]))
            records.append(
                _research_record(
                    "route",
                    record_id=f"ton:omniston:{route_key}",
                    asset_a=token0,
                    asset_b=token1,
                    underlying_resources=resources,
                    # Same single-pool quote shares STON's correlation group.
                    correlation_group=(
                        resources[0]
                        if len(resources) == 1
                        else f"ton:route:{route_key}"
                    ),
                )
            )
    else:
        raise TonSchemaError("unsupported TON discovery resource")
    return _deduplicate(records)


class StonRadarIngestor:
    """Poll a bounded round-robin prefix of STON's whole-universe REST lists.

    No published rate limit is treated as a priority hint, never an unbounded
    polling license. The shared transport owns TLS, response bounds and host
    allowlisting. Keep max_attempts=1 to retain each blind window separately.
    """

    def __init__(
        self,
        transport: Transport,
        *,
        campaign_generation: str,
        max_records: int = 50_000,
        request_timeout_seconds: float = 10.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        omniston: OmnistonReader | None = None,
        journal_path: Path | None = None,
    ) -> None:
        if not campaign_generation or type(max_records) is not int or max_records <= 0:
            raise ValueError("generation and positive record bound are required")
        if not 0 < request_timeout_seconds <= 60:
            raise ValueError("request timeout must be between zero and 60 seconds")
        policy = getattr(transport, "policy", None)
        if policy is not None and getattr(policy, "max_attempts", 1) != 1:
            raise ValueError(
                "TON transport must preserve each attempt with max_attempts=1"
            )
        self.transport = transport
        self.campaign_generation = campaign_generation
        self.max_records = max_records
        self.request_timeout_seconds = request_timeout_seconds
        self.clock = clock
        self.omniston = omniston
        self.journal_path = journal_path
        self.next_cursor = 0

    async def _capture(
        self,
        resource: str,
        request: Mapping[str, Any],
        call: Callable[[], Awaitable[Any]],
        *,
        source: str = "ston.fi",
    ) -> TonDiscoveryEnvelope:
        payload: Any = None
        records: tuple[dict[str, Any], ...] = ()
        negative: tuple[str, ...] = ()
        status: int | None = None
        retry_after: str | None = None
        observed_at = self.clock().astimezone(UTC).isoformat()
        try:
            async with asyncio.timeout(self.request_timeout_seconds):
                response = await call()
            if source == "ston.fi":
                status, headers, payload = response
                retry_after = headers.get("retry-after")
                if status == 429:
                    negative = ("RATE_LIMIT",)
                elif not 200 <= status < 300:
                    negative = ("HTTP_ERROR",)
            else:
                payload = response
            if not negative:
                records = normalize_ston_payload(
                    resource, payload, max_records=self.max_records
                )
        except asyncio.CancelledError:
            raise
        except (TimeoutError, asyncio.TimeoutError):
            negative = ("TIMEOUT",)
        except SanitizedTransportError as error:
            status = error.status_code
            negative = ("RATE_LIMIT" if status == 429 else "TRANSPORT_ERROR",)
        except TonSchemaError as error:
            negative = ("SCHEMA_ERROR", str(error))
        except Exception:
            # Do not persist exception text: injected SDKs may include credentials.
            negative = ("PROVIDER_ERROR",)
        try:
            payload_json = _canonical_json(payload)
        except (ValueError, TypeError, RecursionError):
            payload_json = "null"
            records = ()
            negative = ("SCHEMA_ERROR", "non-replayable provider payload")
        envelope = TonDiscoveryEnvelope(
            source=source,
            source_url=str(request["url"]),
            resource=resource,
            observed_at=observed_at,
            campaign_generation=self.campaign_generation,
            request_hash=_hash(_canonical_json(request)),
            response_hash=_hash(payload_json),
            payload_json=payload_json,
            records_json=_canonical_json(records),
            negative_evidence=negative,
            status_code=status,
            retry_after=retry_after,
        )
        if self.journal_path is not None:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            with self.journal_path.open("a", encoding="utf-8") as stream:
                stream.write(_canonical_json(envelope.to_dict()) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        return envelope

    async def poll(
        self, cursor: int | None = None, budget: int = 3
    ) -> tuple[TonDiscoveryEnvelope, ...]:
        """Budget counts actual provider calls, including optional enrichment."""
        if type(budget) is not int or not 0 <= budget <= 4:
            raise ValueError("TON request budget must be between zero and four")
        start = self.next_cursor if cursor is None else cursor
        if type(start) is not int or not 0 <= start < len(_ENDPOINTS):
            raise ValueError("invalid TON radar cursor")
        result: list[TonDiscoveryEnvelope] = []
        for offset in range(min(budget, len(_ENDPOINTS))):
            resource = _ENDPOINTS[(start + offset) % len(_ENDPOINTS)]
            url = f"https://api.ston.fi/v1/{resource}"
            result.append(
                await self._capture(
                    resource,
                    {"method": "GET", "url": url},
                    partial(self.transport.request, "GET", url),
                )
            )
        self.next_cursor = (start + len(result)) % len(_ENDPOINTS)
        reader = self.omniston
        if reader is not None and len(result) < budget:
            markets = tuple(
                record
                for envelope in result
                for record in envelope.records
                if record["kind"] == "market"
            )
            if markets:
                result.append(
                    await self._capture(
                        "routes",
                        {
                            "method": "READ_ONLY_RFQ",
                            "url": "omniston:injected-reader",
                            "markets": [record["record_id"] for record in markets],
                            "max_routes": self.max_records,
                        },
                        partial(
                            reader.discover_routes, markets, max_routes=self.max_records
                        ),
                        source="omniston",
                    )
                )
        return tuple(result)


def replay_ton_journal(path: Path) -> tuple[TonDiscoveryEnvelope, ...]:
    """Replay only persisted evidence, validating hashes and normalized records."""
    result = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            envelope = TonDiscoveryEnvelope.from_dict(json.loads(line))
            if not envelope.negative_evidence:
                normalized = normalize_ston_payload(
                    envelope.resource, json.loads(envelope.payload_json)
                )
                if _canonical_json(normalized) != envelope.records_json:
                    raise ValueError("TON replay normalized records disagree")
            elif envelope.records:
                raise ValueError("negative TON evidence cannot contain candidates")
            result.append(envelope)
    return tuple(result)
