"""Webhook Configuration for Helius LST Arbitrage Monitoring."""

import os
from typing import Dict, List, Optional, Any

from src.config.addresses import get_enabled_addresses

class WebhookConfig:
    """Configuration for Helius webhooks monitoring LST arbitrage."""

    # LST Token Mints to Monitor
    LST_ADDRESSES = [
        "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",  # JitoSOL
        "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",  # mSOL
        "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",  # bSOL
        "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm",  # INF (Sanctum Infinity)
        "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v",  # JupSOL — Jupiter LST
        "HUBsveNpjo5pWqNkH57QzxjQASdTVXcSK7bVKTSZtcSX",  # hubSOL
        "BonK1YhkXEGLZzwtcvRTip3gAL9nCeQD7ppZBLXhtTs",  # bonkSOL
        "CgnTSoL3DgY9SFHxcLj6CgCgKKoTBr6tp4CPAEWy25DE",  # cgntSOL — Cogent LST
        "vSoLxydx6akxyMD9XEcPvGYNGq6Nn66oqVb3UkGkei7",  # vSOL — Vault LST
        "cPQPBN7WubB3zyQDpzTK2ormx1BMdAym9xkrYUJsctm",  # fwdSOL — Forward staking LST
    ]

    # LST Program IDs — used for program-level activity detection, not token-filtering
    LST_PROGRAMS = [
        "stkitrT1Uoy18Dk1fTrgPw8W6MVzoCfYoAFT4MLsmhq",  # Sanctum Router
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
        "996779v88TxhK6C7H7F5z3u3rL5FvP9SwBeCfFFmCd29",  # mSOL/SOL pool
        "861yXg9vS8SvPCXarsLSdGfZBuUr5mMmZmX2DRNXQKp",  # bSOL/SOL pool (FIX 133)
        "HJPjoWUrhoZzkNfRpHuieeFk9AnbVjTk9Gc5SJRqsQTK",  # INF/SOL pool (FIX 133)
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
        if "your-cloudflare-worker.dev" in webhook_url:
            raise ValueError("CRITICAL: WEBHOOK_URL must be configured in .env for production.")

        # BL-001: Relaxed Helius credit conservation filters with env-configurable thresholds
        min_dex_filter_lamports = int(float(os.getenv("HELIUS_MIN_DEX_FILTER_SOL", "0.5")) * 1e9)
        min_lst_filter_lamports = int(float(os.getenv("HELIUS_MIN_LST_FILTER", "0.1")) * 1e9)

        # Dynamic filtering: use only enabled addresses from addresses.py
        # This prevents wasting Helius credits on disabled/noisy contracts
        enabled_addr_keys = list(get_enabled_addresses().keys())

        return {
            "webhookURL": webhook_url,
            "webhookType": "enhanced",
            "transactionTypes": ["SWAP", "TRANSFER", "CREATE_POOL", "GRADUATION"],
            "accountAddresses": enabled_addr_keys,
            "txnStatus": "success",  # OPTIMIZED: Only listen to successful trades (saves credits)
            "accountFilters": [
                {"accountKey": "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
                 "nativeFilters": [{"min": min_dex_filter_lamports}]},  # DEX filter - Jupiter/Raydium
                {"accountKey": "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
                 "nativeFilters": [{"min": min_dex_filter_lamports}]},  # DEX filter - Orca
                {"accountKey": "stkitrT1Uoy18Dk1fTrgPw8W6MVzoCfYoAFT4MLsmhq",
                 "nativeFilters": [{"min": min_lst_filter_lamports}]},   # LST filter - Sanctum Router
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
            cls.LST_PROGRAMS +
            cls.PARCL_ADDRESSES +
            cls.PYTH_ADDRESSES +
            cls.ORCA_POOL_ADDRESSES
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
            "description": "Multi-Strategy Arbitrage: LST + RWA Monitoring"
        }

# For backward compatibility and easy access
LST_ADDRESSES = WebhookConfig.LST_ADDRESSES
LST_PROGRAMS = WebhookConfig.LST_PROGRAMS
PARCL_ADDRESSES = WebhookConfig.PARCL_ADDRESSES
PYTH_ADDRESSES = WebhookConfig.PYTH_ADDRESSES
WEBHOOK_IDS = WebhookConfig.WEBHOOK_IDS
WEBHOOK_EVENT_TYPES = WebhookConfig.WEBHOOK_EVENT_TYPES
MANAGEMENT_IDS = WebhookConfig.MANAGEMENT_IDS