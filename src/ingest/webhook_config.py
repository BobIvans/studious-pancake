"""Webhook Configuration for Helius LST Arbitrage Monitoring."""

import os
from typing import Dict, List, Optional

class WebhookConfig:
    """Configuration for Helius webhooks monitoring LST arbitrage."""

    # LST Token Addresses to Monitor
    LST_ADDRESSES = [
        "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",  # JitoSOL
        "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",  # mSOL
        "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",  # bSOL
        "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm",  # Sanctum Infinity (INF)
        "stkitrT1Uoy18Dk1fTrgPw8W6MVzoCfYoAFT4MLsmhq"   # Sanctum Router
    ]

    # xStocks Token Addresses for Oracle Lag Monitoring
    XSTOCK_ADDRESSES = [
        "Xsc9qvGR1efVDFGLrVsmkzv3qi45LTBjeUKSPmx9qEh",  # NVDAx
        "XsDoVfqeBukxuZHWhdvWHBhgEHjGNst4MLodqsJHzoB",  # TSLAx
        "XsoCS1uUs1zvS2p7iwtsG3b6fkhpvmwz4GYU3gWAmWHZ", # AAPLx
        "Xs8S1uUs1zvS2p7iwtsG3b6fkhpvmwz4GYU3gWAmWHZ",  # SPYx
        "XspzcW1PRtgf6Wj92HCiZdjzKCyFekVD8P5Ueh3dRMX",  # QQQx
        "Xs7ZdzSHLU9ftNJsii5fCeJhoRWSC32SQGzGQtePxNu",   # COINx
        "XsP7xzNPvEHS1m6qfanPUGjNmdnmsLKEoNAnHjdxxyZ",  # MSTRx
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

    # Active Webhook IDs
    WEBHOOK_IDS = [
        "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg",
        "dbcij3LWUppTiACKHVKtjUi2Vn3JBmXu4quMErSMFpN",
        "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"
    ]

    # Management IDs for programmatic control
    MANAGEMENT_IDS = [
        "d0f65273-6427-48fc-b3cf-b70af928b0fc",
        "8d929e15-b845-4a58-b25a-935eb688c6ac"
    ]

    # Primary management ID
    PRIMARY_MANAGEMENT_ID = "d0f65273-6427-48fc-b3cf-b70af928b0fc"

    # Secondary management ID
    SECONDARY_MANAGEMENT_ID = "8d929e15-b845-4a58-b25a-935eb688c6ac"

    @classmethod
    def get_webhook_config(cls) -> Dict[str, any]:
        """Get the complete webhook configuration for Helius API."""
        webhook_url = os.getenv("WEBHOOK_URL", "https://your-cloudflare-worker.dev/webhook")

        return {
            "webhookURL": webhook_url,
            "webhookType": "enhanced",
            "transactionTypes": ["SWAP", "TRANSFER", "CREATE_POOL", "GRADUATION"],
            "accountAddresses": (
                cls.LST_ADDRESSES +
                cls.XSTOCK_ADDRESSES +
                cls.PARCL_ADDRESSES +
                cls.PYTH_ADDRESSES +
                cls.ORCA_POOL_ADDRESSES
            ),
            "txnStatus": "success",  # OPTIMIZED: Only listen to successful trades (saves credits)
            "accountFilters": [  # Fix 86: Helius credit optimization - min 0.01 SOL native transfer
                {"accountKey": "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H6KCm3nTqK2", "filters": [{"memcmp": {"offset": 0, "bytes": ""}}], "nativeFilters": [{"min": 10000000}]},  # 0.01 SOL
                {"accountKey": "whirLbMiicVdio4qvUfM5KMi3H9L1m1n3v4x2z3y4", "filters": [{"memcmp": {"offset": 0, "bytes": ""}}], "nativeFilters": [{"min": 10000000}]},  # 0.01 SOL
            ],
            "webhookIds": cls.WEBHOOK_IDS,
            "managementIds": cls.MANAGEMENT_IDS
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
    def get_webhook_info(cls) -> Dict[str, any]:
        """Get comprehensive webhook information."""
        all_addresses = (
            cls.LST_ADDRESSES +
            cls.XSTOCK_ADDRESSES +
            cls.PARCL_ADDRESSES +
            cls.PYTH_ADDRESSES +
            cls.ORCA_POOL_ADDRESSES
        )

        return {
            "lst_addresses": cls.LST_ADDRESSES,
            "xstock_addresses": cls.XSTOCK_ADDRESSES,
            "parcl_addresses": cls.PARCL_ADDRESSES,
            "pyth_addresses": cls.PYTH_ADDRESSES,
            "orca_pool_addresses": cls.ORCA_POOL_ADDRESSES,
            "webhook_ids": cls.WEBHOOK_IDS,
            "management_ids": cls.MANAGEMENT_IDS,
            "total_addresses": len(all_addresses),
            "total_webhooks": len(cls.WEBHOOK_IDS),
            "description": "Multi-Strategy Arbitrage: LST + xStocks Oracle Lag + RWA Monitoring"
        }

# For backward compatibility and easy access
LST_ADDRESSES = WebhookConfig.LST_ADDRESSES
XSTOCK_ADDRESSES = WebhookConfig.XSTOCK_ADDRESSES
PARCL_ADDRESSES = WebhookConfig.PARCL_ADDRESSES
PYTH_ADDRESSES = WebhookConfig.PYTH_ADDRESSES
WEBHOOK_IDS = WebhookConfig.WEBHOOK_IDS
MANAGEMENT_IDS = WebhookConfig.MANAGEMENT_IDS