"""Strict Token-2022 mint semantics inspection, never an exact pool receipt.

Layout is pinned to the official token-2022 interface. Account, hook,
confidential-transfer and unreviewed extensions remain unsupported. A mint
inspection cannot substitute for GPR-01's replayed QPR-02 HARD_BOUND receipt.
"""

from dataclasses import asdict, dataclass
import hashlib

import base58

from src.qualification_campaign.identity import digest
from src.research_economic_graph import StartupIdentityPolicy
from src.research_economic_graph.registry import TOKEN_2022_PROGRAM


def authority(raw, *, coption=False):
    if coption:
        tag = int.from_bytes(raw[:4], "little")
        if tag not in (0, 1):
            raise ValueError("MALFORMED_AUTHORITY_OPTION")
        if tag == 0 and any(raw[4:]):
            raise ValueError("NONCANONICAL_ABSENT_AUTHORITY")
        return base58.b58encode(raw[4:]).decode() if tag else None
    return base58.b58encode(raw).decode() if any(raw) else None


@dataclass(frozen=True)
class Token2022SemanticsPolicy:
    identity_policy: StartupIdentityPolicy
    asset_id: str
    mint_authority: str | None
    freeze_authority: str | None
    # Review exact semantics bytes: hashes are NOT generated from observations.
    extension_hashes: tuple[tuple[int, str], ...]
    transfer_fee_config_authority: str | None = None
    withdraw_withheld_authority: str | None = None

    def __post_init__(self):
        items = tuple(sorted(self.extension_hashes))
        if (
            len(items) != len(dict(items))
            or len(items) > 32
            or any(
                type(t) is not int
                or t not in (1, 3, 18, 19)
                or len(h) != 64
                or any(c not in "0123456789abcdef" for c in h)
                for t, h in items
            )
        ):
            raise ValueError("UNSUPPORTED_OR_UNREVIEWED_EXTENSION_POLICY")
        object.__setattr__(self, "extension_hashes", items)

    @property
    def generation(self):
        return digest(asdict(self))


def decode_token2022_mint(data, *, mint, owner):
    if owner != TOKEN_2022_PROGRAM:
        raise ValueError("TOKEN_2022_OWNER_REQUIRED")
    if not isinstance(data, bytes) or not 82 <= len(data) <= 16_384:
        raise ValueError("BOUNDED_TOKEN_2022_MINT_REQUIRED")
    if data[45] != 1:
        raise ValueError("UNINITIALIZED_TOKEN_2022_MINT")
    extensions = {}
    if len(data) != 82:
        if len(data) < 166 or any(data[82:165]) or data[165] != 1:
            raise ValueError("TOKEN_2022_MINT_ACCOUNT_TYPE_INVALID")
        offset = 166
        while offset < len(data):
            tail = data[offset:]
            if not any(tail):
                break
            if len(tail) < 4:
                raise ValueError("MALFORMED_TOKEN_2022_TLV")
            kind, length = int.from_bytes(tail[:2], "little"), int.from_bytes(
                tail[2:4], "little"
            )
            if (
                kind == 0
                or kind in extensions
                or not length
                or offset + 4 + length > len(data)
            ):
                raise ValueError("MALFORMED_OR_DUPLICATE_TOKEN_2022_TLV")
            if kind not in (1, 3, 18, 19):
                raise ValueError("UNSUPPORTED_TOKEN_2022_TRANSFER_SEMANTICS")
            body = data[offset + 4 : offset + 4 + length]
            if (
                (kind == 1 and length != 108)
                or (kind == 3 and length != 32)
                or (kind == 18 and length != 64)
                or (kind == 19 and length < 80)
            ):
                raise ValueError("TOKEN_2022_EXTENSION_LENGTH_INVALID")
            if kind == 18:
                # External metadata needs a separately governed account receipt.
                if base58.b58encode(body[32:64]).decode() != mint:
                    raise ValueError("TOKEN_2022_EXTERNAL_METADATA_UNQUALIFIED")
            if kind == 19:
                if base58.b58encode(body[32:64]).decode() != mint:
                    raise ValueError("TOKEN_2022_METADATA_MINT_MISMATCH")
                cursor = 64

                def text_field():
                    nonlocal cursor
                    if cursor + 4 > len(body):
                        raise ValueError("MALFORMED_TOKEN_2022_METADATA")
                    size = int.from_bytes(body[cursor : cursor + 4], "little")
                    cursor += 4
                    if size > 2048 or cursor + size > len(body):
                        raise ValueError("BOUNDED_TOKEN_2022_METADATA_REQUIRED")
                    body[cursor : cursor + size].decode("utf-8", errors="strict")
                    cursor += size

                for _ in range(3):
                    text_field()
                if cursor + 4 > len(body):
                    raise ValueError("MALFORMED_TOKEN_2022_METADATA")
                count = int.from_bytes(body[cursor : cursor + 4], "little")
                cursor += 4
                if count > 32:
                    raise ValueError("BOUNDED_TOKEN_2022_METADATA_REQUIRED")
                for _ in range(count):
                    text_field()
                    text_field()
                if cursor != len(body):
                    raise ValueError("MALFORMED_TOKEN_2022_METADATA")
            extensions[kind] = body
            if len(extensions) > 32:
                raise ValueError("BOUNDED_TOKEN_2022_EXTENSIONS_REQUIRED")
            offset += 4 + length
    return {
        "mint": mint,
        "owner": owner,
        "decimals": data[44],
        "supply": int.from_bytes(data[36:44], "little"),
        "mint_authority": authority(data[:36], coption=True),
        "freeze_authority": authority(data[46:82], coption=True),
        "extensions": extensions,
        "state_sha256": hashlib.sha256(data).hexdigest(),
    }


def inspect_token2022_semantics(asset, data, owner, *, policy, epoch):
    if (
        not isinstance(policy, Token2022SemanticsPolicy)
        or policy.asset_id != asset.asset_id
    ):
        raise ValueError("REVIEWED_TOKEN_2022_SEMANTICS_POLICY_REQUIRED")
    expected = policy.identity_policy.require(asset)
    if asset.standard != "Token-2022" or type(epoch) is not int or epoch < 0:
        raise ValueError("TOKEN_2022_IDENTITY_OR_EPOCH_INVALID")
    mint = decode_token2022_mint(data, mint=asset.canonical_identifier, owner=owner)
    hashes = tuple(
        sorted(
            (t, hashlib.sha256(v).hexdigest()) for t, v in mint["extensions"].items()
        )
    )
    if (
        mint["decimals"] != expected.decimals
        or mint["mint_authority"] != policy.mint_authority
        or mint["freeze_authority"] != policy.freeze_authority
        or hashes != policy.extension_hashes
        or tuple(str(t) for t, _ in hashes) != expected.extensions
    ):
        raise ValueError("TOKEN_2022_REVIEWED_SEMANTICS_MISMATCH")
    active_fee = {"epoch": epoch, "maximum_fee": 0, "basis_points": 0}
    config = mint["extensions"].get(1)
    if config is not None:
        if (
            authority(config[:32]) != policy.transfer_fee_config_authority
            or authority(config[32:64]) != policy.withdraw_withheld_authority
        ):
            raise ValueError("TOKEN_2022_FEE_AUTHORITY_MISMATCH")

        def schedule(raw):
            row = {
                "epoch": int.from_bytes(raw[:8], "little"),
                "maximum_fee": int.from_bytes(raw[8:16], "little"),
                "basis_points": int.from_bytes(raw[16:18], "little"),
            }
            if row["basis_points"] > 10_000:
                raise ValueError("TOKEN_2022_INVALID_TRANSFER_FEE")
            return row

        older, newer = schedule(config[72:90]), schedule(config[90:108])
        if older["epoch"] > newer["epoch"]:
            raise ValueError("TOKEN_2022_FEE_EPOCH_ORDER_INVALID")
        active_fee = newer if epoch >= newer["epoch"] else older
    result = {k: v for k, v in mint.items() if k != "extensions"}
    result.update(
        extension_hashes=hashes,
        active_transfer_fee=active_fee,
        semantics_policy_generation=policy.generation,
        identity_policy_generation=policy.identity_policy.generation,
        representation_digest=digest(asset.representation),
        exact_pool_receipt=False,
        exact_graph_allowed=False,
        live_authorization=False,
    )
    return result


def transfer_fee(amount, schedule):
    if type(amount) is not int or not 0 <= amount <= 2**64 - 1:
        raise ValueError("BOUNDED_TRANSFER_AMOUNT_REQUIRED")
    bps, maximum = schedule["basis_points"], schedule["maximum_fee"]
    if (
        type(bps) is not int
        or not 0 <= bps <= 10_000
        or type(maximum) is not int
        or not 0 <= maximum <= 2**64 - 1
    ):
        raise ValueError("INVALID_TRANSFER_FEE_SCHEDULE")
    return min(maximum, (amount * bps + 9_999) // 10_000)
