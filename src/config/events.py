"""
Solana & Helius Webhook Events Configuration.
Defines supported event types and maintains the cross-leg event queue trigger.
"""

import asyncio
from enum import Enum, unique
from typing import Optional

# Shared event triggers to avoid circular imports between arb_bot and ingest modules
lst_webhook_trigger: Optional[asyncio.Queue] = None


@unique
class WebhookEventType(str, Enum):
    """Unified enum representing all Helius/Solana event types monitored by the bot."""
    SWAP = "SWAP"
    TRANSFER = "TRANSFER"
    CREATE_POOL = "CREATE_POOL"
    ADD_LIQUIDITY = "ADD_LIQUIDITY"
    REMOVE_LIQUIDITY = "REMOVE_LIQUIDITY"
    GRADUATION = "GRADUATION"
    ACCOUNT_UPDATE = "ACCOUNT_UPDATE"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_string(cls, val: str) -> "WebhookEventType":
        """Safely parse event string, falling back to UNKNOWN on mismatch."""
        try:
            return cls(str(val).upper().strip())
        except ValueError:
            return cls.UNKNOWN
