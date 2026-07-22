"""Webhook Configuration for Helius LST Arbitrage Monitoring."""

import logging
import os
from typing import Any, Dict, List

from src.config.addresses import get_enabled_addresses

logger = logging.getLogger(__name__)


class WebhookConfig:
    """Configuration for Helius webhooks monitoring LST arbitrage."""

    LST_ADDRESSES = [
        "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
        "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",
        "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",
        "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm",
        "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v",
        "HUBsveNpjo5pWqNkH57QzxjQASdTVXcSK7bVKTSZtcSX",
        "BonK1YhkXEGLZzwtcvRTip3gAL9nCeQD7ppZBLXhtTs",
        "CgnTSoL3DgY9SFHxcLj6CgCgKKoTBr6tp4CPAEWy25DE",
        "vSoLxydx6akxyMD9XEcPvGYNGq6Nn66oqVb3UkGkei7",
        "cPQPBN7WubB3zyQDpzTK2ormx1BMdAym9xkrYUJsctm",
    ]

    LST_PROGRAMS = [
        "stkitrT1Uoy18Dk1fTrgPw8W6MVzoCfYoAFT4MLsmhq",
    ]

    PARCL_ADDRESSES = [
        "3parcLrT7WnXAcyPfkCz49oofuuf2guUKkjuFkAhZW8Y",
        "PaRCLKPpkfHQfXTruT8yhEUx5oRNH8z8erBnzEerc8a",
    ]

    PYTH_ADDRESSES = [
        "FsJ3A3u2vn5cTVofAjvy6y5kwABJAqYWp49E5U4g9ZPY",
    ]

    ORCA_POOL_ADDRESSES = [
        "Hp53XEtt4S8SvPCXarsLSdGfZBuUr5mMmZmX2DRNXQKp",
        "996779v88TxhK6C7H7F5z3u3rL5FvP9SwBeCfFFmCd29",
        "861yXg9vS8SvPCXarsLSdGfZBuUr5mMmZmX2DRNXQKp",
        "HJPjoWUrhoZzkNfRpHuieeFk9AnbVjTk9Gc5SJRqsQTK",
    ]

    WEBHOOK_IDS: list[str] = []
    WEBHOOK_EVENT_TYPES: dict[str, list[str]] = {}
    MANAGEMENT_IDS: list[str] = []
    PRIMARY_MANAGEMENT_ID = ""
    SECONDARY_MANAGEMENT_ID = ""

    @classmethod
    def get_webhook_config(cls) -> Dict[str, Any]:
        """Build the management payload; strict validation happens before I/O."""

        webhook_url = os.getenv("WEBHOOK_URL", "").strip()
        auth_header = os.getenv("HELIUS_WEBHOOK_AUTH_HEADER", "").strip()
        if not webhook_url:
            logger.warning(
                "WEBHOOK_URL is not configured; management creation will fail closed"
            )
        if not auth_header:
            logger.warning(
                "HELIUS_WEBHOOK_AUTH_HEADER is not configured; "
                "management creation will fail closed"
            )

        min_dex_filter_lamports = int(
            float(os.getenv("HELIUS_MIN_DEX_FILTER_SOL", "0.5")) * 1e9
        )
        min_lst_filter_lamports = int(
            float(os.getenv("HELIUS_MIN_LST_FILTER", "0.1")) * 1e9
        )
        enabled_addr_keys = list(get_enabled_addresses().keys())

        return {
            "webhookURL": webhook_url,
            "webhookType": "enhanced",
            "transactionTypes": [
                "SWAP",
                "TRANSFER",
                "CREATE_POOL",
                "GRADUATION",
            ],
            "accountAddresses": enabled_addr_keys,
            "authHeader": auth_header or None,
            "txnStatus": "success",
            "accountFilters": [
                {
                    "accountKey": "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
                    "nativeFilters": [{"min": min_dex_filter_lamports}],
                },
                {
                    "accountKey": "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
                    "nativeFilters": [{"min": min_dex_filter_lamports}],
                },
                {
                    "accountKey": "stkitrT1Uoy18Dk1fTrgPw8W6MVzoCfYoAFT4MLsmhq",
                    "nativeFilters": [{"min": min_lst_filter_lamports}],
                },
            ],
            "webhookIds": cls.WEBHOOK_IDS,
            "managementIds": cls.MANAGEMENT_IDS,
            "webhookEventTypes": cls.WEBHOOK_EVENT_TYPES,
        }

    @classmethod
    def get_active_webhooks(cls) -> List[str]:
        return cls.WEBHOOK_IDS.copy()

    @classmethod
    def get_management_ids(cls) -> List[str]:
        return cls.MANAGEMENT_IDS.copy()

    @classmethod
    def is_valid_webhook(cls, webhook_id: str) -> bool:
        return webhook_id in cls.WEBHOOK_IDS

    @classmethod
    def is_management_id(cls, management_id: str) -> bool:
        return management_id in cls.MANAGEMENT_IDS

    @classmethod
    def get_webhook_info(cls) -> Dict[str, Any]:
        all_addresses = (
            cls.LST_ADDRESSES
            + cls.LST_PROGRAMS
            + cls.PARCL_ADDRESSES
            + cls.PYTH_ADDRESSES
            + cls.ORCA_POOL_ADDRESSES
        )
        return {
            "lst_addresses": cls.LST_ADDRESSES,
            "lst_programs": cls.LST_PROGRAMS,
            "parcl_addresses": cls.PARCL_ADDRESSES,
            "pyth_addresses": cls.PYTH_ADDRESSES,
            "orca_pool_addresses": cls.ORCA_POOL_ADDRESSES,
            "webhook_ids": cls.WEBHOOK_IDS,
            "webhook_event_types": cls.WEBHOOK_EVENT_TYPES,
            "management_ids": cls.MANAGEMENT_IDS,
            "total_addresses": len(all_addresses),
            "total_webhooks": len(cls.WEBHOOK_IDS),
            "description": "Multi-Strategy Arbitrage: LST + RWA Monitoring",
        }


LST_ADDRESSES = WebhookConfig.LST_ADDRESSES
LST_PROGRAMS = WebhookConfig.LST_PROGRAMS
PARCL_ADDRESSES = WebhookConfig.PARCL_ADDRESSES
PYTH_ADDRESSES = WebhookConfig.PYTH_ADDRESSES
WEBHOOK_IDS = WebhookConfig.WEBHOOK_IDS
WEBHOOK_EVENT_TYPES = WebhookConfig.WEBHOOK_EVENT_TYPES
MANAGEMENT_IDS = WebhookConfig.MANAGEMENT_IDS
