"""Bounded read-only Move decoder contracts bound to reviewed package ids.

Every decoder binds the exact package, module and type name (via
``bcs.bind_move_type``) before any field is decoded, and parses BCS with
bounded canonical lengths: wrong package, unknown type, truncated or
noncanonical encodings fail closed. Decimal values are always bound back to
the retained ``0x2::coin::CoinMetadata<T>`` BCS, never to a ticker or a
claimed number.

The DeepBook pool layout decoded here is the deterministic reviewed TEST
CONTRACT pinned in ``POOL_DECODER_LAYOUT``. It is a decoder contract for
offline fixtures, not a mainnet layout proof: production qualification still
requires the separately reviewed dynamic-object book/fee layout binding (see
``verification.py``), and this module supplies none.
"""

import base64
import hashlib

from .bcs import bind_move_type, metadata_decimals, move_tag
from .models import coin_type, object_id
from .verification import DecodedPoolState

# Reviewed test-contract layout: seven u64 fields in this exact order, BCS
# ULEB128-encoded, no trailing bytes. Production layouts require a new pin.
POOL_DECODER_LAYOUT = (
    "object_version",
    "lot_size",
    "tick_size",
    "taker_fee_numerator",
    "fee_denominator",
    "bid_depth_units",
    "ask_depth_units",
)
REVIEWED_POOL_MODULE = "pool"
REVIEWED_POOL_TYPE = "Pool"
# The only reviewed fee-semantics label in this slice. Production fee labels
# (dynamic DeepBook taker-fee rules) require an explicit reviewed binding.
REVIEWED_FEE_SEMANTICS = frozenset({"FIXTURE_REVIEWED_CONTRACT"})


def decode_bcs_u64_fields(body, field_names):
    """Decode exactly ``field_names`` canonical ULEB128 u64 values, no extra."""
    if not isinstance(body, bytes):
        raise ValueError("SUI_POOL_STATE_BCS_REQUIRED")
    offset = 0
    values = []
    for _ in field_names:
        value, shift, count = 0, 0, 0
        while True:
            if offset >= len(body) or count >= 10:
                raise ValueError("SUI_TRUNCATED_POOL_STATE_BCS")
            byte = body[offset]
            offset += 1
            count += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                if count > 1 and byte == 0:
                    raise ValueError("SUI_NONCANONICAL_POOL_STATE_BCS_LENGTH")
                break
            shift += 7
        if value > 2**64 - 1:
            raise ValueError("SUI_POOL_STATE_U64_OVERFLOW")
        values.append(value)
    if offset != len(body):
        raise ValueError("SUI_POOL_STATE_BCS_TRAILING_BYTES")
    return dict(zip(field_names, values, strict=True))


def metadata_for_type(checkpoint, expected_type):
    """Find the checkpoint-scoped metadata alias proving exactly this type."""
    expected = move_tag("0x2::coin::CoinMetadata<" + coin_type(expected_type) + ">")
    for alias in ("a", "b"):
        metadata = checkpoint["query"][alias]
        if move_tag(metadata["contents"]["type"]["repr"]) == expected:
            return metadata
    raise ValueError("SUI_POOL_COIN_METADATA_TYPE_MISMATCH")


class DeepBookPoolDecoder:
    """Typed pool-state decoder bound to one reviewed package id.

    ``decode`` returns the gate's ``DecodedPoolState``: package and type
    binding, object version, decimal bindings from actual metadata BCS, and
    the bounded depth/fee fields of the pinned layout.
    """

    def __init__(self, *, expected_package, fee_semantics="FIXTURE_REVIEWED_CONTRACT"):
        object_id(expected_package)
        if fee_semantics not in REVIEWED_FEE_SEMANTICS:
            raise ValueError("SUI_REVIEWED_FEE_SEMANTICS_REQUIRED")
        self.expected_package = object_id(expected_package)
        self.fee_semantics = fee_semantics

    def decode(self, checkpoint, obj, bcs):
        repr_ = obj["asMoveObject"]["contents"]["type"]["repr"]
        _, args = bind_move_type(
            repr_,
            expected_package=self.expected_package,
            expected_module=REVIEWED_POOL_MODULE,
            expected_type=REVIEWED_POOL_TYPE,
        )
        if len(args) != 2 or len(set(args)) != 2:
            raise ValueError("SUI_TWO_POOL_TYPE_ARGUMENTS_REQUIRED")
        coin_types = tuple(coin_type(arg) for arg in args)
        fields = decode_bcs_u64_fields(bcs, POOL_DECODER_LAYOUT)
        if fields["fee_denominator"] < 1 or (
            fields["taker_fee_numerator"] >= fields["fee_denominator"]
        ):
            raise ValueError("SUI_POOL_FEE_FRACTION_INVALID")
        decimals = []
        metadata_hashes = []
        for t in coin_types:
            metadata = metadata_for_type(checkpoint, t)
            decoded = metadata_decimals(
                base64.b64decode(metadata["contents"]["bcs"], validate=True),
                address=metadata["address"],
                tag=metadata["contents"]["type"]["repr"],
                expected_coin_type=t,
            )
            decimals.append(decoded)
            metadata_hashes.append(
                hashlib.sha256(
                    base64.b64decode(metadata["contents"]["bcs"], validate=True)
                ).hexdigest()
            )
        state_hash = hashlib.sha256(bcs).hexdigest()
        return DecodedPoolState(
            pool_id=obj["address"],
            package_id=self.expected_package,
            object_version=fields["object_version"],
            checkpoint=checkpoint["sequenceNumber"],
            move_type=repr_,
            coin_types=coin_types,
            decimals=(decimals[0], decimals[1]),
            bid_depth_units=fields["bid_depth_units"],
            ask_depth_units=fields["ask_depth_units"],
            taker_fee_numerator=fields["taker_fee_numerator"],
            fee_denominator=fields["fee_denominator"],
            lot_size=fields["lot_size"],
            tick_size=fields["tick_size"],
            fee_semantics=self.fee_semantics,
            state_bcs_sha256=state_hash,
            depth_bcs_sha256=state_hash,
            fee_bcs_sha256=state_hash,
            metadata_bcs_sha256=(metadata_hashes[0], metadata_hashes[1]),
        )
