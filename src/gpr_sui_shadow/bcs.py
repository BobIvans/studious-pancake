"""Bounded standard 0x2 CoinMetadata content decoding; never ticker inference."""

import re

from .models import coin_type, object_id


def move_tag(tag):
    if not isinstance(tag, str) or len(tag) > 1024 or any(c.isspace() for c in tag):
        raise ValueError("SUI_INVALID_MOVE_TAG")
    return re.sub(
        r"0x([a-fA-F0-9]{1,64})(?=::)", lambda m: "0x" + m[1].lower().zfill(64), tag
    )


def metadata_decimals(body, *, address, tag, expected_coin_type):
    expected_tag = move_tag(
        "0x2::coin::CoinMetadata<" + coin_type(expected_coin_type) + ">"
    )
    if (
        move_tag(tag) != expected_tag
        or not isinstance(body, bytes)
        or not 37 <= len(body) <= 16_384
    ):
        raise ValueError("SUI_EXACT_COIN_METADATA_TYPE_BCS_REQUIRED")
    if body[:32].hex() != object_id(address)[2:]:
        raise ValueError("SUI_METADATA_UID_BCS_MISMATCH")
    offset = 33

    def length():
        nonlocal offset
        value, shift, count = 0, 0, 0
        while True:
            if offset >= len(body) or count >= 5:
                raise ValueError("SUI_INVALID_METADATA_BCS_LENGTH")
            byte = body[offset]
            offset += 1
            count += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                if count > 1 and byte == 0:
                    raise ValueError("SUI_NONCANONICAL_METADATA_BCS_LENGTH")
                return value
            shift += 7

    def string():
        nonlocal offset
        size = length()
        if size > 4096 or offset + size > len(body):
            raise ValueError("SUI_INVALID_METADATA_BCS_STRING")
        body[offset : offset + size].decode("utf-8", errors="strict")
        offset += size

    # UID, u8 decimals, Move String name/symbol/description, Option<Url> icon.
    for _ in range(3):
        string()
    option = length()
    if option == 1:
        string()
    elif option != 0:
        raise ValueError("SUI_INVALID_METADATA_BCS_ICON_OPTION")
    if offset != len(body):
        raise ValueError("SUI_METADATA_BCS_TRAILING_BYTES")
    return body[32]
