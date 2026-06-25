"""Webhook Configuration for Helius LST Arbitrage Monitoring."""

import os
from typing import Dict, List, Optional, Any

from src.config.addresses import get_enabled_addresses

class WebhookConfig:
    """Configuration for Helius webhooks monitoring LST arbitrage."""

    # LST Token Addresses to Monitor
    LST_ADDRESSES = [
        "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",  # JitoSOL
        "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",  # mSOL
        "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",  # bSOL
        "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm",  # INF (Sanctum Infinity)
        "stkitrT1Uoy18Dk1fTrgPw8W6MVzoCfYoAFT4MLsmhq",  # Sanctum Router program
        "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v",  # JupSOL — Jupiter LST
        "HUBsveNpjo5pWqNkH57QzxjQASdTVXcSK7bVKTSZtcSX",  # hubSOL
        "BonK1YhkXEGLZzwtcvRTip3gAL9nCeQD7ppZBLXhtTs",  # bonkSOL
        "CgnTSoL3DgY9SFHxcLj6CgCgKKoTBr6tp4CPAEWy25DE",  # cgntSOL — Cogent LST
        "vSoLxydx6akxyMD9XEcPvGYNGq6Nn66oqVb3UkGkei7",  # vSOL — Vault LST
        "cPQPBN7WubB3zyQDpzTK2ormx1BMdAym9xkrYUJsctm",  # fwdSOL — Forward staking LST
    ]

    # Parcl Protocol Addresses for RWA Monitoring
    PARCL_ADDRESSES = [
        "3parcLrT7WnXAcyPfkCz49oofuuf2guUKkjuFkAhZW8Y",  # Parcl v3 Program
        "PaRCLKPpkfHQfXTruT8yhEUx5oRNH8z8erBnzEerc8a",  # Parcl Pyth
    ]

    # Pyth Oracle Program for Real-Time Price Feeds
    PYTH_ADDRESSES = [
        "FsJ3A3u2vn5cTVofAjvy6y5kwABJAqYWp49E5U4g9ZPY",  # Pyth Program ID
    ]

    # Orca Pool Addresses for LST Depeg Monitoring
    ORCA_POOL_ADDRESSES = [
        "Hp53XEtt4S8SvPCXarsLSdGfZBuUr5mMmZmX2DRNXQKp",  # JitoSOL/SOL pool
    ]

    # Active Webhook IDs and the Helius event classes they monitor.
    # Task 17: Pure Code-Driven Webhook Authentication (No .env IDs)
    # We now rely strictly on HMAC authentication or API keys.
    WEBHOOK_IDS = []

    WEBHOOK_EVENT_TYPES = {}

    # Management IDs for programmatic control
    MANAGEMENT_IDS = []

    # Primary management ID
    PRIMARY_MANAGEMENT_ID = ""

    # Secondary management ID
    SECONDARY_MANAGEMENT_ID = ""

    @classmethod
    def get_webhook_config(cls) -> Dict[str, Any]:
        """Get the complete webhook configuration for Helius API."""
        webhook_url = os.getenv("WEBHOOK_URL", "https://your-cloudflare-worker.dev/webhook")
        
        # Dynamic filtering: use only enabled addresses from addresses.py
        # This prevents wasting Helius credits on disabled/noisy contracts
        enabled_addr_keys = list(get_enabled_addresses().keys())
        
        return {
            "webhookURL": webhook_url,
            "webhookType": "enhanced",
            "transactionTypes": ["SWAP", "TRANSFER", "CREATE_POOL", "GRADUATION"],
            "accountAddresses": enabled_addr_keys,
            "txnStatus": "success",  # OPTIMIZED: Only listen to successful trades (saves credits)
            "accountFilters": [  # Phase 49: Helius credit conservation — hard filter
                {"accountKey": "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
                 "nativeFilters": [{"min": 50_000_000_000}]},  # 50 SOL threshold - Jupiter
                {"accountKey": "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
                 "nativeFilters": [{"min": 50_000_000_000}]},  # 50 SOL threshold - Orca
                {"accountKey": "stkitrT1Uoy18Dk1fTrgPw8W6MVzoCfYoAFT4MLsmhq",
                 "nativeFilters": [{"min": 5_000_000_000}]},   # 5 SOL threshold - Sanctum
            ],
            "webhookIds": cls.WEBHOOK_IDS,
            "managementIds": cls.MANAGEMENT_IDS,
            "webhookEventTypes": cls.WEBHOOK_EVENT_TYPES
        }

    @classmethod
    def get_active_webhooks(cls) -> List[str]:
        """Get list of active webhook IDs."""
        return cls.WEBHOOK_IDS.copy()

    @classmethod
    def get_management_ids(cls) -> List[str]:
        """Get list of management IDs."""
        return cls.MANAGEMENT_IDS.copy()

    @classmethod
    def is_valid_webhook(cls, webhook_id: str) -> bool:
        """Check if a webhook ID is valid/active."""
        return webhook_id in cls.WEBHOOK_IDS

    @classmethod
    def is_management_id(cls, management_id: str) -> bool:
        """Check if a management ID is valid."""
        return management_id in cls.MANAGEMENT_IDS

    @classmethod
    def get_webhook_info(cls) -> Dict[str, Any]:
        """Get comprehensive webhook information."""
        all_addresses = (
            cls.LST_ADDRESSES +
            cls.PARCL_ADDRESSES +
            cls.PYTH_ADDRESSES +
            cls.ORCA_POOL_ADDRESSES
        )

        return {
            "lst_addresses": cls.LST_ADDRESSES,
            "parcl_addresses": cls.PARCL_ADDRESSES,
            "pyth_addresses": cls.PYTH_ADDRESSES,
            "orca_pool_addresses": cls.ORCA_POOL_ADDRESSES,
            "webhook_ids": cls.WEBHOOK_IDS,
            "webhook_event_types": cls.WEBHOOK_EVENT_TYPES,
            "management_ids": cls.MANAGEMENT_IDS,
            "total_addresses": len(all_addresses),
            "total_webhooks": len(cls.WEBHOOK_IDS),
            "description": "Multi-Strategy Arbitrage: LST + RWA Monitoring"
        }

# For backward compatibility and easy access
LST_ADDRESSES = WebhookConfig.LST_ADDRESSES
PARCL_ADDRESSES = WebhookConfig.PARCL_ADDRESSES
PYTH_ADDRESSES = WebhookConfig.PYTH_ADDRESSES
WEBHOOK_IDS = WebhookConfig.WEBHOOK_IDS
WEBHOOK_EVENT_TYPES = WebhookConfig.WEBHOOK_EVENT_TYPES
MANAGEMENT_IDS = WebhookConfig.MANAGEMENT_IDS