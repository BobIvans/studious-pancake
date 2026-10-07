"""Read-only chain assertions. Sui uses an injected gRPC/Core evidence reader."""

from dataclasses import asdict, replace
import json
from typing import Callable

from src.assets.resolution.evidence import Evidence, digest
from src.assets.resolution.resolver import (
    CandidateAsset,
    ChainAssetProof,
    canonical_identifier,
)


class SolanaMintVerifier:
    def __init__(self, fetcher, endpoints: tuple[str, ...]):
        if not 1 <= len(endpoints) <= 3 or len(set(endpoints)) != len(endpoints):
            raise ValueError("one to three distinct read-only RPC endpoints required")
        self.fetcher, self.endpoints = fetcher, endpoints
        self.negative_evidence: list[Evidence] = []

    def __call__(self, candidate: CandidateAsset) -> tuple[ChainAssetProof, ...]:
        if candidate.chain != "solana":
            raise ValueError("Solana mint verifier requires Solana identity")
        proofs = []
        for index, endpoint in enumerate(self.endpoints):
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [
                    candidate.identifier,
                    {"encoding": "jsonParsed", "commitment": "finalized"},
                ],
            }
            payload, evidence = self.fetcher.fetch(
                endpoint, f"solana-rpc-{index}", body=request
            )
            if evidence.negative_reason:
                self.negative_evidence.append(evidence)
                continue
            try:
                response = json.loads(payload["body"])
                if "error" in response:
                    raise ValueError("RPC error")
                result = response["result"]
                position = result["context"]["slot"]
                account = result["value"]
                if account is None:
                    raise ValueError("mint account missing")
                parsed = account["data"]["parsed"]
                if parsed["type"] != "mint":
                    raise ValueError("account is not a mint")
                info = parsed["info"]
                if info["isInitialized"] is not True:
                    raise ValueError("uninitialized mint")
                extensions = tuple(
                    sorted(row["extension"] for row in info.get("extensions", ()))
                )
                chain_evidence = replace(evidence, slot_or_checkpoint=position)
                self.fetcher.store.append(chain_evidence, payload)
                proofs.append(
                    ChainAssetProof(
                        "solana",
                        candidate.identifier,
                        info["decimals"],
                        account["owner"],
                        True,
                        chain_evidence,
                        extensions,
                        info["mintAuthority"],
                        info["freezeAuthority"],
                        int(info["supply"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                self.negative_evidence.append(
                    replace(evidence, negative_reason="invalid_mint_rpc_schema")
                )
        return tuple(proofs)


class SuiCoreCoinVerifier:
    """Typed bridge for current Sui gRPC/Core, never legacy JSON-RPC.

    Reader must fetch coin metadata and full package/type existence/version at
    one checkpoint and retain its raw provider payload in the evidence store.
    Missing installed Core bridge is a blocker, not manufactured chain proof.
    """

    def __init__(self, reader: Callable[[str], tuple[dict, Evidence]]):
        self.reader = reader

    def __call__(self, candidate: CandidateAsset) -> tuple[ChainAssetProof, ...]:
        if candidate.chain != "sui":
            raise ValueError("Sui verifier requires full Move coin identity")
        payload, evidence = self.reader(candidate.identifier)
        if evidence.negative_reason:
            return ()
        if (
            payload["transport"] not in ("grpc", "graphql-core")
            or payload["schema"] != "dynamic-universe.sui-coin-proof.v1"
            or canonical_identifier("sui", payload["coin_type"]) != candidate.identifier
        ):
            raise ValueError("unknown Sui Core proof schema or type")
        return (
            ChainAssetProof(
                "sui",
                candidate.identifier,
                payload["decimals"],
                payload["program_or_package"],
                payload["type_exists"] is True,
                evidence,
                package_version=payload["package_version"],
            ),
        )
