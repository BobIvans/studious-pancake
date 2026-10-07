"""V2.2 non-token transport contracts. Templates never manufacture endpoints."""

from dataclasses import dataclass
import json
from pathlib import Path

from src.qualification_campaign.identity import digest
from .models import EvidenceState, ExecutionClass, Heat, ResearchRelation


@dataclass(frozen=True)
class TransportTransformation:
    transformation_id: str
    kind: str
    source_representation: str | None
    target_representation: str | None
    economic_asset: str | None
    canonical_transport_id: str | None
    execution_class: ExecutionClass
    evidence_state: EvidenceState
    provenance_ref: str
    signal_class: ExecutionClass | None = None
    atomic_graph_allowed: bool = False

    def __post_init__(self):
        object.__setattr__(
            self, "execution_class", ExecutionClass(self.execution_class)
        )
        object.__setattr__(self, "evidence_state", EvidenceState(self.evidence_state))
        if self.signal_class is not None:
            object.__setattr__(self, "signal_class", ExecutionClass(self.signal_class))
        if (
            not self.transformation_id
            or not self.kind
            or self.atomic_graph_allowed is not False
            or self.execution_class
            not in (ExecutionClass.REBALANCE_ONLY, ExecutionClass.CROSS_CHAIN_SIGNAL)
            or self.evidence_state != EvidenceState.IDENTIFIER_VERIFIED
            or self.signal_class not in (None, ExecutionClass.CROSS_CHAIN_SIGNAL)
        ):
            raise ValueError("transport must stay research-only and non-atomic")

    def relation(self) -> ResearchRelation | None:
        if self.source_representation is None:
            return None  # A template has no concrete edge or fake token node.
        refs = (self.source_representation,) + (
            (self.target_representation,) if self.target_representation else ()
        )
        return ResearchRelation(
            "transport:" + self.transformation_id,
            self.kind,
            refs,
            Heat.COLD,
            self.execution_class,
            self.evidence_state,
            provenance_refs=(self.provenance_ref,),
            reference=self.canonical_transport_id,
        )


def load_transformations(registry, path: Path):
    raw = json.loads(path.read_text())
    if raw.get("schema_version") != "gpr.transformation-registry.v2.2":
        raise ValueError("V2.2 transformation registry required")
    safety = raw["safety"]
    if safety != {
        "default_execution_class": "REBALANCE_ONLY",
        "default_evidence_state": "IDENTIFIER_VERIFIED",
        "atomic_graph_allowed": False,
    }:
        raise ValueError("non-atomic transformation safety required")
    rows = sorted(raw["transformations"], key=lambda r: r["transformation_id"])
    configuration = {**raw, "transformations": rows}
    generation = digest(configuration)
    result = []
    for row in rows:
        if any(
            row.get(key) is not False
            for key in (
                "creates_new_solana_mint",
                "creates_token_identity",
                "creates_transport_identity",
            )
            if key in row
        ):
            raise ValueError("transport cannot manufacture token identities")
        refs = []
        for key in ("source_representation", "target_representation"):
            value = row.get(key)
            if value is not None:
                asset = registry.resolve(value)
                if asset.asset_id != value or not asset.identifier_verified:
                    raise ValueError("exact resolved representation endpoint required")
                if (
                    row.get("economic_asset") is not None
                    and asset.economic_asset != row["economic_asset"]
                ):
                    raise ValueError("transport economic asset mismatch")
            refs.append(value)
        if refs[0] is None and not row["kind"].endswith("_TEMPLATE"):
            raise ValueError("concrete transport requires its source representation")
        result.append(
            TransportTransformation(
                row["transformation_id"],
                row["kind"],
                refs[0],
                refs[1],
                row.get("economic_asset"),
                row.get("canonical_transport_id"),
                row["execution_class"],
                row["evidence_state"],
                f"{path.name}#sha256={generation}",
                row.get("signal_class"),
                row["atomic_graph_allowed"],
            )
        )
    if len({t.transformation_id for t in result}) != len(result):
        raise ValueError("duplicate transformation identifier")
    return configuration, tuple(result)
