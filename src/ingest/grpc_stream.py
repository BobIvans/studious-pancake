"""
Yellowstone gRPC Adapter for Zero-Latency Streaming
Live implementation using grpcio + yellowstone_grpc_proto (PyPI package).
Replaces WebSocket accountSubscribe with sub-50ms binary gRPC streaming from
Helius/Triton relay nodes directly out of validator RAM.

NOTE: This is OPTIONAL for free tier (Helius Webhook only mode). If protobuf
deps are missing, the bot continues without gRPC streaming.
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Yellowstone-protobuf bootstrap (graceful, not required) ──────────────────────
_GEYSER_AVAILABLE = False
_geyser_pb2 = None
_geyser_pb2_grpc = None
_IMPORT_ERR = ""
_grpc = None  # Will be set if available

try:
    import grpc as _grpc
    from yellowstone_grpc_proto import geyser_pb2 as _geyser_pb2           # type: ignore[import]
    from yellowstone_grpc_proto import geyser_pb2_grpc as _geyser_pb2_grpc   # type: ignore[import]
    _GEYSER_AVAILABLE = True

    # ── Channel keep-alive options (HTTP/2 on gRPC) ───────────────────────────────
    _KEEPALIVE_MS        = 20_000
    _KEEPALIVE_TIMEOUT_MS = 10_000
    _KEEPALIVE_PERMIT    = True
    _MAX_PING_STRIKES    = 0
except ImportError as _import_err:
    _IMPORT_ERR = str(_import_err)
    logger.info(
        "ℹ️ Yellowstone gRPC not installed - using Helius Webhook-only mode (free tier)"
    )


class YellowstoneStream:
    """Live Yellowstone gRPC streaming client — 20-40 ms faster than WebSocket.

    Parameters
    ----------
    grpc_endpoint: ``host:port`` of the relay, e.g.
        ``"yellowstone.helius.rpcpool.com:443"``.
    api_key: Optional bearer token injected as gRPC metadata.
    """

    def __init__(self, grpc_endpoint: str, api_key: Optional[str] = None) -> None:
        if not _GEYSER_AVAILABLE:
            logger.error(
                "YellowstoneStream instantiated without protobuf deps. "
                "Install yellowstone-grpc-proto and grpcio first."
            )

        self.grpc_endpoint    = grpc_endpoint
        self.api_key          = api_key
        self.channel: Optional[Any] = None
        self.stub:    Optional[Any] = None
        self.running          = False
        self._retry_task: Optional[asyncio.Task] = None
        self._dead            = False

        # ── Callback registries ──────────────────────────────────────────────
        self.account_callbacks: Dict[str, List[Callable]]   = {}
        self.program_callbacks: Dict[str, List[Callable]]   = {}

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return _GEYSER_AVAILABLE

    async def connect(self) -> None:
        """Open gRPC channel and start the subscribe / redelivery loop."""
        if not _GEYSER_AVAILABLE:
            logger.error(
                "Yellowstone stream connect ABORTED — grpc/proto deps missing. "
                f"Root cause: {_IMPORT_ERR}"
            )
            return

        self.running = True
        self._dead   = False
        self._retry_task = asyncio.create_task(self._retry_loop())

    async def disconnect(self) -> None:
        """Shut down gracefully — cancel retry loop, close gRPC channel."""
        self._dead   = True
        self.running = False
        if self._retry_task is not None:
            self._retry_task.cancel()
            try:
                await self._retry_task
            except asyncio.CancelledError:
                pass
            self._retry_task = None
        if self.channel is not None:
            try:
                await self.channel.close()
            except Exception:
                pass
            self.channel = None
            self.stub    = None

    # ── Callback registration ──────────────────────────────────────────────────

    def register_account_callback(
        self, account_address: str, callback: Callable
    ) -> None:
        if account_address not in self.account_callbacks:
            self.account_callbacks[account_address] = []
        self.account_callbacks[account_address].append(callback)

    def register_program_callback(
        self, program_id: str, callback: Callable
    ) -> None:
        if program_id not in self.program_callbacks:
            self.program_callbacks[program_id] = []
        if callback not in self.program_callbacks[program_id]:
            self.program_callbacks[program_id].append(callback)

    # ── Core retry / reconnect loop ────────────────────────────────────────────

    async def _retry_loop(self) -> None:
        """Exponential-backoff outer loop: reconnect on any stream failure."""
        backoff = 1.0
        while self.running and not self._dead:
            try:
                await self._run_stream()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    f"Yellowstone stream error ({exc!r}) — "
                    f"reconnecting in {backoff:.1f}s"
                )
            if not self.running or self._dead:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, 30.0)

    async def _run_stream(self) -> None:
        """Open a single gRPC channel, send Subscribe, drain the response stream."""
        if not _GEYSER_AVAILABLE:
            return

        metadata: List[tuple] = (
            [("authorization", f"Bearer {self.api_key}")]
            if self.api_key
            else []
        )

        options = [
            ("grpc.keepalive_time_ms",              _KEEPALIVE_MS),
            ("grpc.keepalive_timeout_ms",           _KEEPALIVE_TIMEOUT_MS),
            ("grpc.keepalive_permit_without_calls", _KEEPALIVE_PERMIT),
            ("grpc.http2.max_ping_strikes",         _MAX_PING_STRIKES),
        ]

        channel = _grpc.aio.secure_channel(
            self.grpc_endpoint,
            _grpc.ssl_channel_credentials(),
            options=options,
        )
        self.channel = channel
        self.stub     = _geyser_pb2_grpc.GeyserStub(channel)

        req = self._build_subscribe_from_registries()
        logger.info(
            f"Yellowstone gRPC ▶ streaming from {self.grpc_endpoint}  "
            f"| accounts={len(self.account_callbacks)}  "
            f"| programs={len(self.program_callbacks)}"
        )

        async for update in self.stub.Subscribe(req, metadata=metadata or None):  # type: ignore[call-arg]
            if self._dead or not self.running:
                break
            await self._dispatch(update)

    # ── Subscribe-request assembly ──────────────────────────────────────────────

    def _build_subscribe_from_registries(self) -> Any:
        """Build a SubscribeRequest proto from the current callback registries."""

        def _acct_filter() -> Any:
            return _geyser_pb2.SubscribeRequestFilterAccounts(
                owner=None, filters=[]
            )

        accounts: Dict[str, Any] = {
            addr: _acct_filter() for addr in self.account_callbacks
        }

        programs: Dict[str, Any] = {
            pid: _geyser_pb2.SubscribeRequestFilterPrograms(
                account=_acct_filter(),
                logs=True,
            )
            for pid in self.program_callbacks
        }

        return _geyser_pb2.SubscribeRequest(
            accounts=accounts,
            accounts_data_slice=[],
            programs=programs,
        )

    # ── Update dispatch ─────────────────────────────────────────────────────────

    async def _dispatch(self, update: Any) -> None:
        """Route an incoming SubscribeUpdate to all matching callbacks."""
        which = update.WhichOneof("update")
        if which == "account":
            await self._route_account(update.account)
        elif which == "pong":
            # Relay acknowledged our ping — nothing to do
            pass

    async def _route_account(self, account_update: Any) -> None:
        """Push an account update to every registered callback for that pubkey."""
        try:
            raw:   bytes = account_update.account.data
            pubkey: str  = account_update.account.pubkey
        except Exception:
            return

        for cb in self.account_callbacks.get(pubkey, []):
            try:
                await cb({
                    "pubkey":  pubkey,
                    "owner":   account_update.account.owner,
                    "data":    raw,
                    "slot":    account_update.account.slot,
                })
            except Exception as exc:
                logger.debug(f"Yellowstone account callback error [{pubkey[:8]}]: {exc}")

    # ── Health / stats ──────────────────────────────────────────────────────────

    def get_connection_stats(self) -> Dict[str, Any]:
        return {
            "endpoint":            self.grpc_endpoint,
            "connected":           self.channel is not None,
            "accounts_subscribed": len(self.account_callbacks),
            "programs_subscribed": len(self.program_callbacks),
            "latency_ms_target":   "<50",
            "proto_available":     _GEYSER_AVAILABLE,
        }

    async def health_check(self) -> bool:
        if self.channel is None or self.stub is None:
            return False
        try:
            resp = await self.stub.Ping(                       # type: ignore[misc]
                _geyser_pb2.PingRequest(num=0),                 # type: ignore[misc]
                timeout=2.0,
            )
            return resp is not None
        except Exception:
            return False
