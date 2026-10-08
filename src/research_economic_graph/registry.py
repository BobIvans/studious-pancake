"""Typed V2.1/V2.2 catalog and campaign seeds; no inferred token identities."""

from __future__ import annotations

import json
from pathlib import Path
import re
from types import MappingProxyType
from dataclasses import dataclass

from src.qualification_campaign.identity import canonical_bytes, digest
from .models import AssetIdentity, EvidenceState, ResearchRelation, SyntheticPath
from .transformations import TransportTransformation, load_transformations

SPL_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
DEFAULT_PACK = (
    Path(__file__).resolve().parents[2]
    / "docs/roadmap/gpr-parallel-radar-rnd-2026-10-06"
)


def canonical_key(chain: str, identifier: str) -> tuple[str, str]:
    if (
        not isinstance(identifier, str)
        or not identifier
        or identifier != identifier.strip()
    ):
        raise ValueError("canonical identifier required")
    if chain == "sui-mainnet":
        match = re.fullmatch(
            r"0x([0-9a-fA-F]{1,64})::([A-Za-z_][A-Za-z0-9_]*)::([A-Za-z_][A-Za-z0-9_]*)",
            identifier,
        )
        if not match:
            raise ValueError("invalid Move coin type")
        identifier = f"0x{match[1].lower().zfill(64)}::{match[2]}::{match[3]}"
    return chain, identifier


def object_id(value: str) -> str:
    if not re.fullmatch(r"0x[0-9a-f]{1,64}", value):
        raise ValueError("invalid Sui pool identifier")
    return "0x" + value[2:].zfill(64)


def pool_representations(registry, relation: str) -> tuple[str, str]:
    keys = relation.split("/")
    if len(keys) != 2 or keys[0] == keys[1]:
        raise ValueError("DeepBook pool requires two distinct representations")
    return (
        registry.resolve("sui-mainnet:" + keys[0]).asset_id,
        registry.resolve("sui-mainnet:" + keys[1]).asset_id,
    )


class AssetRegistry:
    def __init__(self, raw: dict, *, source_ref: str = "ASSET_REGISTRY_V2.json"):
        if raw.get("schema_version") not in (
            "gpr.asset-registry.v2.1",
            "gpr.asset-registry.v2.2",
        ):
            raise ValueError("GPR V2.1/V2.2 registry required")
        self.schema_version = raw["schema_version"]
        if (
            raw.get("safety", {}).get("default_runtime_enabled") is not False
            or raw.get("safety", {}).get("default_exact_graph_allowed") is not False
        ):
            raise ValueError("research-only registry required")
        rows = sorted(raw["assets"], key=lambda r: (r["chain"], r["asset_key"]))
        if not rows or len(rows) > 1024:
            raise ValueError("bounded registry required")
        configuration = {**raw, "assets": rows}
        self.generation = digest(configuration)
        self._configuration_json = canonical_bytes(configuration).decode()
        assets, identifiers, aliases = {}, {}, {}
        for row in rows:
            chain, key, identifier = row["chain"], row["asset_key"], row["canonical_id"]
            labels = {
                key.upper(),
                *(alias.upper() for alias in row.get("legacy_aliases", ())),
            }
            if labels & {"CCTP", "WORMHOLE", "WORMHOLE_ROUTE"} or (
                chain == "solana-mainnet"
                and labels & {"USDT0", "USDT0_SOLANA", "USDT0_LEGACY_MESH"}
            ):
                raise ValueError(
                    "transport mechanisms cannot create fake asset identities"
                )
            if chain not in ("solana-mainnet", "sui-mainnet", "ton-mainnet"):
                raise ValueError("unsupported research chain")
            standard = row["standard"]
            program = (
                {"SPL": SPL_TOKEN_PROGRAM, "Token-2022": TOKEN_2022_PROGRAM}.get(
                    standard
                )
                if chain == "solana-mainnet"
                else identifier if standard == "Move" else None
            )
            asset = AssetIdentity(
                asset_id=f"{chain}:{key}",
                asset_key=key,
                chain=chain,
                canonical_identifier=identifier,
                token_program_or_move_type=program,
                decimals=row.get("decimals"),
                economic_asset=row["economic_asset_key"],
                representation_kind=row["representation"],
                origin_chain=row.get("origin_chain"),
                bridge=row.get("bridge"),
                issuer=row.get("issuer"),
                standard=standard,
                verification_state=row["verification_status"],
                verification_sources=(
                    f"{source_ref}#sha256={self.generation}",
                    "ASSET_PROVENANCE_V2.md",
                ),
                identity_generation=self.generation,
                legacy_aliases=tuple(row.get("legacy_aliases", ())),
                note=row.get("note", ""),
                runtime_enabled=row["runtime_enabled"],
                exact_graph_allowed=row["exact_graph_allowed"],
            )
            if asset.asset_id in assets:
                raise ValueError("duplicate representation key")
            assets[asset.asset_id] = asset
            if identifier is not None:
                identity_key = canonical_key(chain, identifier)
                if identity_key in identifiers:
                    raise ValueError("canonical representation alias collision")
                identifiers[identity_key] = asset
            for alias in asset.legacy_aliases:
                alias_key = f"{chain}:{alias}"
                if alias_key in aliases:
                    raise ValueError("ambiguous legacy alias")
                aliases[alias_key] = asset
        if set(assets) & set(aliases):
            raise ValueError("alias shadows a representation")
        self.assets = MappingProxyType(assets)
        self.identifiers = MappingProxyType(identifiers)
        self.aliases = MappingProxyType(aliases)

    @classmethod
    def load(cls, path: Path = DEFAULT_PACK / "ASSET_REGISTRY_V2.json"):
        return cls(json.loads(path.read_text()))

    def resolve(self, qualified_ref: str) -> AssetIdentity:
        """Research lookup requires a chain-qualified key, including aliases."""
        if qualified_ref in self.assets:
            return self.assets[qualified_ref]
        if qualified_ref in self.aliases:
            return self.aliases[qualified_ref]
        raise ValueError("unknown or unqualified representation reference")

    @property
    def configuration(self) -> dict:
        """Canonical input for the unchanged QPR-01 CampaignManifest factory."""
        return json.loads(self._configuration_json)

    def by_identifier(self, chain: str, identifier: str) -> AssetIdentity:
        try:
            return self.identifiers[canonical_key(chain, identifier)]
        except KeyError as exc:
            raise ValueError("identifier is not in registry") from exc


@dataclass(frozen=True)
class DeepBookPoolReference:
    pool_id: str
    canonical_object_id: str
    representations: tuple[str, str]
    provenance_ref: str
    evidence_state: EvidenceState = EvidenceState.IDENTIFIER_VERIFIED
    runtime_enabled: bool = False
    exact_graph_allowed: bool = False

    def __post_init__(self):
        if (
            self.canonical_object_id != object_id(self.pool_id)
            or self.evidence_state != EvidenceState.IDENTIFIER_VERIFIED
            or self.runtime_enabled is not False
            or self.exact_graph_allowed is not False
        ):
            raise ValueError("DeepBook identifiers are research-only")


@dataclass(frozen=True)
class CampaignSeed:
    relations: tuple[ResearchRelation, ...]
    pools: tuple[DeepBookPoolReference, ...]
    generation: str
    configuration_json: str = ""
    transformations: tuple[TransportTransformation, ...] = ()

    @property
    def configuration(self) -> dict:
        if not self.configuration_json:
            raise ValueError("seed configuration unavailable for synthetic/manual seed")
        return json.loads(self.configuration_json)

    @classmethod
    def load(cls, registry: AssetRegistry, pack: Path = DEFAULT_PACK):
        v22 = registry.schema_version == "gpr.asset-registry.v2.2"
        family_file = (
            "FIRST_CAMPAIGN_FAMILIES_V2_2.json"
            if v22
            else "FIRST_CAMPAIGN_FAMILIES_V2_1.json"
        )
        families = json.loads((pack / family_file).read_text())
        books = json.loads((pack / "SUI_DEEPBOOK_POOLS_V2_1.json").read_text())
        if (
            families.get("schema_version")
            != (
                "gpr.first-campaign-families.v2.2"
                if v22
                else "gpr.first-campaign-families.v2.1"
            )
            or books.get("schema_version") != "gpr.sui-deepbook-pools.v2.1"
        ):
            raise ValueError("matching GPR corpus generation required")
        safety = books["safety"]
        if (
            safety["evidence_state"] != "IDENTIFIER_VERIFIED"
            or safety["runtime_enabled"] is not False
            or safety["exact_graph_allowed"] is not False
        ):
            raise ValueError("read-only DeepBook seeds required")
        family_rows = sorted(families["families"], key=lambda r: r["id"])
        pool_rows = sorted(books["pools"], key=lambda r: r["pool_id"])
        configuration = {
            "registry": registry.generation,
            "families": {**families, "families": family_rows},
            "deepbook": {**books, "pools": pool_rows},
        }
        transformations = ()
        if v22:
            transport_configuration, transformations = load_transformations(
                registry, pack / "TRANSFORMATION_REGISTRY_V2_2.json"
            )
            configuration["transformations"] = transport_configuration
        generation = digest(configuration)
        pools = tuple(
            DeepBookPoolReference(
                r["pool_id"],
                object_id(r["pool_id"]),
                pool_representations(registry, r["relation"]),
                f"SUI_DEEPBOOK_POOLS_V2_1.json#sha256={generation}",
            )
            for r in pool_rows
        )
        if len({p.canonical_object_id for p in pools}) != len(pools):
            raise ValueError("duplicate DeepBook pool")
        relations = []
        for row in family_rows:
            chain = row["chain"]

            def ref(key):
                return registry.resolve(
                    key if ":" in key else f"{chain}:{key}"
                ).asset_id

            refs = tuple(ref(k) for k in row["assets"])
            paths = []
            for expression in row.get("synthetic_paths", ()):
                keys = (
                    expression.split(" -> ")
                    if " -> " in expression
                    else (
                        ["PYUSD", "USDC", "USDG"]
                        if expression == "PYUSD/USDC ÷ USDG/USDC"
                        else None
                    )
                )
                if keys is None:
                    raise ValueError("unresolved synthetic path")
                paths.append(SyntheticPath(tuple(ref(k) for k in keys), expression))
            pool_ids = tuple(row.get("deepbook_pool_ids", ())) + (
                (row["deepbook_pool_id"],) if "deepbook_pool_id" in row else ()
            )
            for pool_id in pool_ids:
                if not any(
                    p.pool_id == pool_id and set(p.representations) <= set(refs)
                    for p in pools
                ):
                    raise ValueError("family pool/representation mismatch")
            if row["evidence_state"] != "IDENTIFIER_VERIFIED" or not all(
                registry.resolve(r).identifier_verified for r in refs
            ):
                raise ValueError("seed is not identifier-verified")
            relations.append(
                ResearchRelation(
                    relation_id=row["id"],
                    relation_class=row["relation_class"],
                    representations=refs,
                    heat=row["heat"],
                    execution_class=row["execution_class"],
                    evidence_state=row["evidence_state"],
                    anchor_types=tuple(row["anchor_types"]),
                    direct_venues=tuple(row.get("venues", ())),
                    known_pool_or_book_ids=pool_ids,
                    synthetic_paths=tuple(paths),
                    provenance_refs=(f"{family_file}#sha256={generation}",),
                    reference=row.get("anchor_source") or row.get("oracle_reference"),
                    frictions=tuple(row.get("frictions", ())),
                )
            )
        if len({r.relation_id for r in relations}) != len(relations):
            raise ValueError("duplicate family")
        return cls(
            tuple(relations),
            pools,
            generation,
            canonical_bytes(configuration).decode(),
            transformations,
        )
