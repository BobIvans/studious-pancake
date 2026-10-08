import asyncio
import json
import sys
import argparse
import base64
from dataclasses import asdict
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from src.qualification_campaign.profiles import public_rpc_profile
from src.qualification_campaign.transport import campaign_transport
from src.qualification_campaign.identity import digest
from src.provider_governance import (
    ProviderGovernance,
    AdmissionRequest,
    ProviderOperation,
)
from src.market.native_cpmm_capture import GovernedNativeCpmmCollector
from src.lending.jupiter_lend import (
    JUPITER_FLASHLOAN_ADMIN_PDA,
    JUPITER_LEND_FLASHLOAN_PROGRAM_ID,
    JUPITER_LEND_UPSTREAM_COMMIT,
    JUPITER_LEND_FLASHLOAN_IDL_BLOB,
    decode_flashloan_admin_state,
)
from src.gpr_sui_shadow.campaign import default_profiles
from src.gpr_sui_shadow.sources import CHECKPOINT_QUERY


async def capture(output):
    profile = public_rpc_profile()
    reports = []
    async with campaign_transport({profile.hostname}) as transport:
        governance = ProviderGovernance(
            {
                profile.profile_id: profile.entitlement(
                    expires_at_epoch_seconds=int(time.time()) + 300
                )
            }
        )
        reader = GovernedNativeCpmmCollector(governance, transport, profile=profile)
        for method, params in [
            ("getGenesisHash", []),
            (
                "getMultipleAccounts",
                [
                    [
                        str(JUPITER_FLASHLOAN_ADMIN_PDA),
                        str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID),
                        "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD",
                    ],
                    {"encoding": "base64", "commitment": "finalized"},
                ],
            ),
        ]:
            row = {
                "chain": "solana",
                "endpoint": profile.endpoint,
                "method": method,
                "params": params,
                "request_hash": digest({"method": method, "params": params}),
                "observed_at_ns": time.time_ns(),
                "qualification": "SMOKE_ONLY",
                "profile": asdict(profile),
                "source_generation": profile.generation,
                "sign_enabled": False,
                "send_enabled": False,
            }
            try:
                row["response"] = await reader._rpc(method, params)
            except Exception as exc:
                row["error_type"] = type(exc).__name__
                row["error"] = str(exc)
            row["response_hash"] = digest(row.get("response"))
            reports.append(row)
    pins = json.loads((ROOT / "config/gpr03_sui_source_pins.json").read_text())
    profiles = default_profiles(pins)
    profile = next(p for p in profiles if p.source_kind == "graphql")
    async with campaign_transport({profile.hostname}) as transport:
        governance = ProviderGovernance(
            {profile.profile_id: profile.entitlement(int(time.time()) + 300)}
        )
        governance.bind_transport(transport)
        body = {"query": CHECKPOINT_QUERY}
        request = AdmissionRequest(
            "r02-checkpoint-read",
            profile.profile_id,
            ProviderOperation.BACKFILL,
            digest(body),
            "r02-readonly",
            governance.clock() + 20,
            expected_generation=profile.quota_generation,
        )
        row = {
            "chain": "sui",
            "endpoint": profile.endpoint,
            "method": "GraphQL checkpoint",
            "request_body": body,
            "request_hash": digest(body),
            "observed_at_ns": time.time_ns(),
            "qualification": "SMOKE_ONLY",
            "profile": asdict(profile),
            "source_generation": profile.generation,
            "sign_enabled": False,
            "send_enabled": False,
        }
        try:
            status, headers, response = await governance.execute_physical(
                request,
                lambda: transport.request("POST", profile.endpoint, json_body=body),
                credential_ref=profile.credential_ref,
                credential_generation=profile.credential_generation,
            )
            row.update(http_status=status, response=response)
        except Exception as exc:
            row.update(error_type=type(exc).__name__, error=str(exc))
        row["response_hash"] = digest(row.get("response"))
        reports.append(row)
    envelope = {
        "schema_version": "r02.prerequisite-capture.v1",
        "execution_authority": "NONE",
        "qualified_edges": [],
        "records": reports,
        "records_sha256": digest(reports),
    }
    with output.open("x") as stream:
        stream.write(json.dumps(envelope, indent=2) + "\n")
    print(json.dumps(replay(envelope), indent=2))


def replay(envelope):
    if envelope["schema_version"] != "r02.prerequisite-capture.v1":
        raise ValueError("CAPTURE_SCHEMA_MISMATCH")
    if envelope["records_sha256"] != digest(envelope["records"]):
        raise ValueError("CAPTURE_HASH_MISMATCH")
    if envelope["qualified_edges"] or envelope["execution_authority"] != "NONE":
        raise ValueError("CAPTURE_CANNOT_GRANT_AUTHORITY")
    admin = None
    for row in envelope["records"]:
        if row["response_hash"] != digest(row.get("response")) or row[
            "source_generation"
        ] != digest(row["profile"]):
            raise ValueError("RECORD_HASH_OR_GENERATION_MISMATCH")
        if (
            row["sign_enabled"] is not False
            or row["send_enabled"] is not False
            or row["qualification"] != "SMOKE_ONLY"
        ):
            raise ValueError("READ_ONLY_CAPTURE_REQUIRED")
        request_body = (
            row["request_body"]
            if row["method"] == "GraphQL checkpoint"
            else {"method": row["method"], "params": row["params"]}
        )
        if row["request_hash"] != digest(request_body):
            raise ValueError("REQUEST_HASH_MISMATCH")
        if row["method"] == "getGenesisHash" and "response" in row:
            if (
                row["response"].get("result")
                != "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
            ):
                raise ValueError("GENESIS_MISMATCH")
        if row["method"] == "getMultipleAccounts" and "response" in row:
            if row["request_hash"] != digest(
                {"method": row["method"], "params": row["params"]}
            ):
                raise ValueError("REQUEST_HASH_MISMATCH")
            if row["params"][0][0] != str(JUPITER_FLASHLOAN_ADMIN_PDA):
                raise ValueError("ADMIN_ADDRESS_MISMATCH")
            if row["params"][1] != {"encoding": "base64", "commitment": "finalized"}:
                raise ValueError("FINALIZED_BASE64_REQUIRED")
            account = row["response"]["result"]["value"][0]
            if (
                account["owner"] != str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID)
                or account["executable"] is not False
            ):
                raise ValueError("ADMIN_OWNER_MISMATCH")
            state = decode_flashloan_admin_state(
                base64.b64decode(account["data"][0], validate=True)
            )
            admin = {
                k: str(v) if k in ("authority", "liquidity_program") else v
                for k, v in asdict(state).items()
            }
    return {
        "jupiter_admin": admin,
        "source_commit": JUPITER_LEND_UPSTREAM_COMMIT,
        "idl_blob": JUPITER_LEND_FLASHLOAN_IDL_BLOB,
        "qualified_edges": [],
        "status": (
            "BLOCKED_MISSING_PINNED_RESERVE_ABI"
            if admin is not None
            else "NETWORK_STATE_UNAVAILABLE"
        ),
        "execution_authority": "NONE",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Governed read-only prerequisite capture; never a live capital qualifier."
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    if args.replay:
        print(json.dumps(replay(json.loads(args.replay.read_text())), indent=2))
    elif args.output:
        asyncio.run(capture(args.output))
    else:
        parser.error("require --output or --replay")
