"""Read-only OpenLineage RunEvent projection for Studious runtime evidence.

This module serializes an evidenced operation into OpenLineage's core event
shape. It does not emit HTTP requests, copy raw market payloads, or infer
input/output lineage from event attributes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from importlib.resources import files
import json
import re
from typing import Mapping, Sequence
from urllib.parse import quote
import uuid

from jsonschema import Draft202012Validator

from src.contracts.registry import get_schema_registry
from src.kernel import canonical_json_bytes
from src.observability.events import EventEnvelope

OPENLINEAGE_RUN_EVENT_SCHEMA_ID = "intelligence.openlineage-run-event.v1"
OPENLINEAGE_CORE_SCHEMA_URL = (
    "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent"
)
FACET_SCHEMA_RESOURCE = "openlineage_facets.v1.json"
FACET_SCHEMA_COMMIT = "6ae925f9560305b0a6c987e08c83e4e263e04cb1"
FACET_SCHEMA_BASE_URL = (
    "https://raw.githubusercontent.com/BobIvans/studious-pancake/"
    f"{FACET_SCHEMA_COMMIT}/src/resources/{FACET_SCHEMA_RESOURCE}"
)
FACET_DEFINITIONS = {
    "studious_runtime_context": "StudiousRuntimeContextFacet",
    "studious_strategy_context": "StudiousStrategyContextFacet",
    "studious_block_context": "StudiousBlockContextFacet",
    "studious_data_quality": "StudiousDataQualityFacet",
    "studious_lineage_edges": "StudiousLineageEdgesFacet",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REPO_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class OpenLineageProjectionError(ValueError):
    """Raised when an OpenLineage projection is incomplete or unsupported."""


class OpenLineageEventType(str, Enum):
    START = "START"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    ABORT = "ABORT"
    FAIL = "FAIL"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class DatasetRef:
    namespace: str
    name: str

    def __post_init__(self) -> None:
        if not self.namespace.strip() or not self.name.strip():
            raise OpenLineageProjectionError(
                "dataset namespace and name must be non-empty"
            )
        if len(self.namespace) > 1024 or len(self.name) > 1024:
            raise OpenLineageProjectionError("dataset identity exceeds limits")

    def to_payload(self, facets: Mapping[str, object] | None = None) -> dict[str, object]:
        result: dict[str, object] = {
            "namespace": self.namespace,
            "name": self.name,
        }
        if facets:
            result["facets"] = dict(facets)
        return result


@dataclass(frozen=True, slots=True)
class StrategyContext:
    strategy_id: str
    strategy_version: str
    strategy_family: str | None = None

    def __post_init__(self) -> None:
        if not self.strategy_id.strip() or not self.strategy_version.strip():
            raise OpenLineageProjectionError(
                "strategy ID and version must be non-empty"
            )


@dataclass(frozen=True, slots=True)
class BlockContext:
    chain_id: str
    canonicality: str
    finality: str
    network: str | None = None
    block_number: int | None = None
    block_hash: str | None = None
    transaction_hash: str | None = None
    transaction_index: int | None = None
    log_index: int | None = None
    contract_address: str | None = None
    deployment_version: str | None = None

    def __post_init__(self) -> None:
        if not self.chain_id:
            raise OpenLineageProjectionError("block context requires chain_id")
        if self.canonicality not in {"UNKNOWN", "OBSERVED", "CANONICAL", "REORGED"}:
            raise OpenLineageProjectionError("unsupported block canonicality")
        if self.finality not in {"UNKNOWN", "OPTIMISTIC", "SAFE", "FINALIZED"}:
            raise OpenLineageProjectionError("unsupported block finality")
        for name, value in (
            ("block_number", self.block_number),
            ("transaction_index", self.transaction_index),
            ("log_index", self.log_index),
        ):
            if value is not None and (type(value) is not int or value < 0):
                raise OpenLineageProjectionError(f"{name} must be non-negative")


@dataclass(frozen=True, slots=True)
class DataQualityContext:
    source_mode: str
    provider_id: str | None = None
    adapter_id: str | None = None
    adapter_version: str | None = None
    schema_id: str | None = None
    schema_version: str | None = None
    cursor: str | None = None
    watermark: str | None = None
    event_time: str | None = None
    ingest_time: str | None = None
    freshness_ms: int | None = None
    coverage_ratio: float | None = None
    gap_refs: tuple[str, ...] = ()
    correction_kind: str | None = None
    normalization_version: str | None = None
    raw_payload_ref: str | None = None
    raw_payload_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.source_mode not in {
            "STREAMING",
            "POLL_ONLY",
            "ONE_SHOT",
            "UNAVAILABLE",
        }:
            raise OpenLineageProjectionError("unsupported source mode")
        if self.freshness_ms is not None and (
            type(self.freshness_ms) is not int or self.freshness_ms < 0
        ):
            raise OpenLineageProjectionError("freshness_ms must be non-negative")
        if self.coverage_ratio is not None and not 0 <= self.coverage_ratio <= 1:
            raise OpenLineageProjectionError("coverage_ratio must be between 0 and 1")
        if self.correction_kind not in {None, "original", "correction", "retraction"}:
            raise OpenLineageProjectionError("unsupported correction kind")
        if self.raw_payload_sha256 is not None and not _SHA256_RE.fullmatch(
            self.raw_payload_sha256
        ):
            raise OpenLineageProjectionError("raw payload hash must be SHA-256")


@dataclass(frozen=True, slots=True)
class ExplicitLineageEdge:
    source: DatasetRef
    target: DatasetRef
    provenance: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.provenance:
            raise OpenLineageProjectionError("lineage edge provenance is required")
        normalized = tuple(sorted(set(self.evidence_refs)))
        if not normalized or any(not item for item in normalized):
            raise OpenLineageProjectionError(
                "lineage edge requires at least one evidence reference"
            )
        object.__setattr__(self, "evidence_refs", normalized)


def _producer_uri(repo_sha: str) -> str:
    if not _REPO_SHA_RE.fullmatch(repo_sha):
        raise OpenLineageProjectionError("repo_sha must be a 40-character Git SHA")
    return (
        "https://github.com/BobIvans/studious-pancake/blob/"
        f"{repo_sha}/src/intelligence/openlineage.py"
    )


def _facet_schema_url(facet_name: str) -> str:
    if facet_name not in FACET_DEFINITIONS:
        raise OpenLineageProjectionError(f"unknown Studious facet: {facet_name}")
    definition = FACET_DEFINITIONS[facet_name]
    return f"{FACET_SCHEMA_BASE_URL}#/$defs/{quote(definition, safe='')}"


def _facet(
    *,
    name: str,
    producer_uri: str,
    properties: Mapping[str, object],
) -> dict[str, object]:
    return {
        "_producer": producer_uri,
        "_schemaURL": _facet_schema_url(name),
        **dict(properties),
    }


def _event_time(occurred_at_utc_ns: int) -> str:
    if type(occurred_at_utc_ns) is not int or occurred_at_utc_ns <= 0:
        raise OpenLineageProjectionError("event timestamp must be positive nanoseconds")
    seconds, nanoseconds = divmod(occurred_at_utc_ns, 1_000_000_000)
    try:
        base = datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise OpenLineageProjectionError("event timestamp is out of range") from exc
    return f"{base:%Y-%m-%dT%H:%M:%S}.{nanoseconds:09d}Z"


def _run_id(envelope: EventEnvelope) -> str:
    identity = envelope.attempt_id or (
        f"{envelope.logical_opportunity_id}:{envelope.plan_hash}:"
        f"{envelope.attempt_generation}"
    )
    seed = (
        f"studious-pancake:{envelope.runtime_id}:{envelope.aggregate_id}:"
        f"{identity}:{envelope.attempt_generation}"
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def _quality_facet(
    context: DataQualityContext,
    *,
    producer_uri: str,
) -> dict[str, object]:
    properties: dict[str, object] = {"source_mode": context.source_mode}
    for name in (
        "provider_id",
        "adapter_id",
        "adapter_version",
        "schema_id",
        "schema_version",
        "cursor",
        "watermark",
        "event_time",
        "ingest_time",
        "freshness_ms",
        "coverage_ratio",
        "correction_kind",
        "normalization_version",
        "raw_payload_ref",
        "raw_payload_sha256",
    ):
        value = getattr(context, name)
        if value is not None:
            properties[name] = value
    if context.gap_refs:
        properties["gap_refs"] = list(context.gap_refs)
    return _facet(
        name="studious_data_quality",
        producer_uri=producer_uri,
        properties=properties,
    )


def _block_facet(
    context: BlockContext,
    *,
    producer_uri: str,
) -> dict[str, object]:
    properties: dict[str, object] = {
        "chain_id": context.chain_id,
        "canonicality": context.canonicality,
        "finality": context.finality,
    }
    for name in (
        "network",
        "block_number",
        "block_hash",
        "transaction_hash",
        "transaction_index",
        "log_index",
        "contract_address",
        "deployment_version",
    ):
        value = getattr(context, name)
        if value is not None:
            properties[name] = value
    return _facet(
        name="studious_block_context",
        producer_uri=producer_uri,
        properties=properties,
    )


def _read_facet_schema() -> dict[str, object]:
    resource = files("src.resources").joinpath(FACET_SCHEMA_RESOURCE)
    try:
        value = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OpenLineageProjectionError("custom facet schema cannot be loaded") from exc
    if not isinstance(value, dict) or not isinstance(value.get("$defs"), dict):
        raise OpenLineageProjectionError("custom facet schema is malformed")
    Draft202012Validator.check_schema(value)
    return value


def validate_openlineage_run_event(payload: object) -> None:
    """Validate the local RunEvent envelope and every emitted Studious custom facet."""
    get_schema_registry().validate_payload(
        OPENLINEAGE_RUN_EVENT_SCHEMA_ID,
        payload,
    )
    if not isinstance(payload, Mapping):
        raise OpenLineageProjectionError("RunEvent payload must be an object")
    schema_document = _read_facet_schema()
    definitions = schema_document["$defs"]
    if not isinstance(definitions, Mapping):
        raise OpenLineageProjectionError("facet definitions must be an object")

    def validate_facets(
        values: object,
        *,
        supported: Mapping[str, str],
    ) -> None:
        if values is None:
            return
        if not isinstance(values, Mapping):
            raise OpenLineageProjectionError("facets must be an object")
        for facet_name, definition_name in supported.items():
            value = values.get(facet_name)
            if value is None:
                continue
            wrapper = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$defs": definitions,
                "$ref": f"#/$defs/{definition_name}",
            }
            Draft202012Validator(wrapper).validate(value)

    run = payload.get("run")
    job = payload.get("job")
    if not isinstance(run, Mapping) or not isinstance(job, Mapping):
        raise OpenLineageProjectionError("RunEvent requires run and job objects")
    validate_facets(
        run.get("facets"),
        supported={
            "studious_runtime_context": FACET_DEFINITIONS[
                "studious_runtime_context"
            ],
            "studious_strategy_context": FACET_DEFINITIONS[
                "studious_strategy_context"
            ],
            "studious_block_context": FACET_DEFINITIONS["studious_block_context"],
        },
    )
    validate_facets(
        job.get("facets"),
        supported={
            "studious_lineage_edges": FACET_DEFINITIONS["studious_lineage_edges"]
        },
    )
    for collection_name in ("inputs", "outputs"):
        collection = payload.get(collection_name)
        if not isinstance(collection, Sequence) or isinstance(collection, (str, bytes)):
            raise OpenLineageProjectionError(f"{collection_name} must be an array")
        for dataset in collection:
            if not isinstance(dataset, Mapping):
                raise OpenLineageProjectionError("dataset must be an object")
            validate_facets(
                dataset.get("facets"),
                supported={
                    "studious_data_quality": FACET_DEFINITIONS[
                        "studious_data_quality"
                    ]
                },
            )


def project_event(
    envelope: EventEnvelope,
    *,
    event_type: OpenLineageEventType,
    job_namespace: str,
    job_name: str,
    repo_sha: str,
    inputs: Sequence[DatasetRef],
    outputs: Sequence[DatasetRef],
    lineage_edges: Sequence[ExplicitLineageEdge] = (),
    strategy: StrategyContext | None = None,
    block: BlockContext | None = None,
    dataset_quality: Mapping[DatasetRef, DataQualityContext] | None = None,
) -> dict[str, object]:
    """Project one EventEnvelope into a validated OpenLineage RunEvent.

    Inputs, outputs, event type and lineage edges are caller-supplied explicitly.
    The projector never infers them from EventEnvelope.attributes.
    """
    if not job_namespace.strip() or not job_name.strip():
        raise OpenLineageProjectionError("job namespace and name are required")
    producer_uri = _producer_uri(repo_sha)
    event_type = OpenLineageEventType(event_type)

    input_refs = tuple(inputs)
    output_refs = tuple(outputs)
    if len(input_refs) > 1024 or len(output_refs) > 1024:
        raise OpenLineageProjectionError("dataset count exceeds OpenLineage export limit")
    if len(set(input_refs)) != len(input_refs):
        raise OpenLineageProjectionError("duplicate input dataset")
    if len(set(output_refs)) != len(output_refs):
        raise OpenLineageProjectionError("duplicate output dataset")

    quality = dataset_quality or {}
    declared_datasets = set(input_refs) | set(output_refs)
    if not set(quality).issubset(declared_datasets):
        raise OpenLineageProjectionError(
            "data-quality facet references an undeclared dataset"
        )

    edges = tuple(lineage_edges)
    edge_keys = tuple((edge.source, edge.target) for edge in edges)
    if len(edge_keys) != len(set(edge_keys)):
        raise OpenLineageProjectionError("duplicate explicit lineage edge")
    input_set = set(input_refs)
    output_set = set(output_refs)
    for edge in edges:
        if edge.source not in input_set or edge.target not in output_set:
            raise OpenLineageProjectionError(
                "lineage edge endpoints must be declared input and output datasets"
            )

    evidence_ref_sha256 = None
    if envelope.evidence_ref is not None and _SHA256_RE.fullmatch(
        envelope.evidence_ref.digest
    ):
        evidence_ref_sha256 = envelope.evidence_ref.digest

    runtime_context: dict[str, object] = {
        "event_id": envelope.event_id,
        "event_payload_sha256": envelope.payload_digest(),
        "event_type": envelope.event_type.value,
        "stage": envelope.stage,
        "outcome": envelope.outcome.value,
        "environment": envelope.environment.value,
        "runtime_id": envelope.runtime_id,
        "logical_opportunity_id": envelope.logical_opportunity_id,
        "aggregate_id": envelope.aggregate_id,
        "plan_hash": envelope.plan_hash,
        "attempt_generation": envelope.attempt_generation,
        "attempt_id": envelope.attempt_id,
        "sequence_no": envelope.sequence_no,
        "trace_id": envelope.trace_id,
        "correlation_id": envelope.correlation_id,
        "provider_id": envelope.provider_id,
        "venue_id": envelope.venue_id,
        "reason_code": (
            envelope.reason_code.value if envelope.reason_code is not None else None
        ),
        "config_checksum": (
            envelope.config_checksum
            if envelope.config_checksum != "unknown"
            else None
        ),
        "contract_fixture_version": envelope.contract_fixture_version,
        "evidence_ref_sha256": evidence_ref_sha256,
    }
    run_facets: dict[str, object] = {
        "studious_runtime_context": _facet(
            name="studious_runtime_context",
            producer_uri=producer_uri,
            properties=runtime_context,
        )
    }
    if strategy is not None:
        strategy_properties: dict[str, object] = {
            "strategy_id": strategy.strategy_id,
            "strategy_version": strategy.strategy_version,
            "live_authorized": False,
        }
        if strategy.strategy_family is not None:
            strategy_properties["strategy_family"] = strategy.strategy_family
        run_facets["studious_strategy_context"] = _facet(
            name="studious_strategy_context",
            producer_uri=producer_uri,
            properties=strategy_properties,
        )
    if block is not None:
        run_facets["studious_block_context"] = _block_facet(
            block,
            producer_uri=producer_uri,
        )

    def dataset_payload(reference: DatasetRef) -> dict[str, object]:
        quality_context = quality.get(reference)
        dataset_facets: dict[str, object] = {}
        if quality_context is not None:
            dataset_facets["studious_data_quality"] = _quality_facet(
                quality_context,
                producer_uri=producer_uri,
            )
        return reference.to_payload(dataset_facets or None)

    job_facets: dict[str, object] = {}
    if edges:
        entries = [
            {
                "source": {"namespace": edge.source.namespace, "name": edge.source.name},
                "target": {"namespace": edge.target.namespace, "name": edge.target.name},
                "provenance": edge.provenance,
                "evidence_refs": list(edge.evidence_refs),
            }
            for edge in edges
        ]
        job_facets["studious_lineage_edges"] = _facet(
            name="studious_lineage_edges",
            producer_uri=producer_uri,
            properties={"entries": entries},
        )

    payload: dict[str, object] = {
        "eventType": event_type.value,
        "eventTime": _event_time(envelope.occurred_at_utc_ns),
        "producer": producer_uri,
        "schemaURL": OPENLINEAGE_CORE_SCHEMA_URL,
        "run": {
            "runId": _run_id(envelope),
            "facets": run_facets,
        },
        "job": {
            "namespace": job_namespace,
            "name": job_name,
            "facets": job_facets,
        },
        "inputs": [dataset_payload(item) for item in input_refs],
        "outputs": [dataset_payload(item) for item in output_refs],
    }
    validate_openlineage_run_event(payload)
    return payload


def serialize_run_event(
    envelope: EventEnvelope,
    **projection: object,
) -> str:
    """Return canonical JSON for one validated OpenLineage RunEvent."""
    payload = project_event(envelope, **projection)  # type: ignore[arg-type]
    return canonical_json_bytes(payload).decode("utf-8")
