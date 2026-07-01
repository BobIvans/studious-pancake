"""Data Aggregator for Flash Loan Bot - Unified Event Logging and Analytics."""

import sqlite3
import orjson
import asyncio
import time
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import logging
import aiosqlite
from pathlib import Path
import src.ingest.shared_state as shared_state

logger = logging.getLogger(__name__)


class DataAggregator:
    """Unified data collection and analytics for the arbitrage bot."""

    def __init__(self, db_path: str = "bot_history.db"):
        self.db_path = db_path
        self.write_queue = asyncio.Queue(maxsize=5000)
        self.write_task = None
        self.running = False
        self._ensure_db_exists()

    def _ensure_db_exists(self):
        """Create database and tables if they don't exist."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        cursor = conn.cursor()

        # Enable WAL mode to prevent locking
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA cache_size=-2000;")  # 2MB cache
        cursor.execute("PRAGMA temp_store=MEMORY;")
        cursor.execute("PRAGMA busy_timeout=5000;") # Ждать до 5 секунд снятия лока

        # Main events table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                webhook_id TEXT,
                transaction_signature TEXT,
                input_data TEXT,  -- JSON
                parsed_opportunity TEXT,  -- JSON
                simulation_result TEXT,  -- JSON
                execution_result TEXT,  -- JSON
                metadata TEXT  -- JSON
            )
        """
        )

        # Aggregated stats table for historical data
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY,
                total_events INTEGER DEFAULT 0,
                opportunities_found INTEGER DEFAULT 0,
                opportunities_executed INTEGER DEFAULT 0,
                successful_trades INTEGER DEFAULT 0,
                total_pnl_sol REAL DEFAULT 0.0,
                avg_execution_time_ms REAL DEFAULT 0.0,
                top_pairs TEXT,  -- JSON array of {"pair": "count"}
                created_at REAL DEFAULT (strftime('%s', 'now'))
            )
        """
        )

        # Create indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON events(timestamp)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_event_type ON events(event_type)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_webhook_id ON events(webhook_id)"
        )

        # Fix 63: Schema versioning table — prevents OperationalError on schema changes
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """
        )
        cursor.execute("SELECT MAX(version) FROM schema_version")
        row = cursor.fetchone()
        current_version = row[0] if row[0] else 0
        if current_version < 1:
            cursor.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (1)")
            logger.info("Schema migrated to version 1")

        # Phase 6: Paper trades table — normalized cost breakdown for backtest analysis
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                slot BIGINT,
                blockhash TEXT,
                route TEXT,
                token_in TEXT,
                token_out TEXT,
                amount_lamports BIGINT,
                gross_revenue_lamports BIGINT,
                flashloan_fee_lamports BIGINT,
                dex_fee_lamports BIGINT,
                slippage_bps INTEGER,
                compute_cost_lamports BIGINT,
                network_fee_lamports BIGINT,
                priority_fee_lamports BIGINT,
                jito_tip_lamports BIGINT,
                ata_rent_lamports BIGINT,
                total_cost_lamports BIGINT,
                net_profit_lamports BIGINT,
                roi_pct REAL,
                decision TEXT
            )
        """
        )

        # Phase 49: In-Flight Bundle Tracking table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS inflight_bundles (
                bundle_id TEXT PRIMARY KEY,
                sent_at REAL NOT NULL,
                tx_sigs_json TEXT NOT NULL,
                deducted_sol REAL NOT NULL,
                tip_lamports INTEGER NOT NULL,
                status TEXT NOT NULL,
                finalized_at REAL
            )
        """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_inflight_status ON inflight_bundles(status)")

        conn.commit()
        conn.close()

    async def log_inflight_bundle(self, bundle_id: str, signatures: list[str], deducted_sol: float, tip_lamports: int):
        """
        Instantly persist an inflight bundle to SQLite.
        Uses synchronous sqlite3 (not write_queue) for crash safety.
        """
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.execute(
                "INSERT OR REPLACE INTO inflight_bundles (bundle_id, sent_at, tx_sigs_json, deducted_sol, tip_lamports, status) VALUES (?, ?, ?, ?, ?, ?)",
                (bundle_id, time.time(), orjson.dumps(signatures).decode(), deducted_sol, tip_lamports, 'sent'),
            )
            conn.commit()
            conn.close()
            logger.debug(f"Inflight bundle logged: {bundle_id[:12]} (tip={tip_lamports}, deducted={deducted_sol:.8f} SOL)")
        except Exception as e:
            logger.error(f"Failed to log inflight bundle: {e}")

    async def update_inflight_status(self, bundle_id: str, new_status: str):
        """Update the status of an inflight bundle."""
        try:
            import sqlite3
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.execute(
                "UPDATE inflight_bundles SET status = ?, finalized_at = ? WHERE bundle_id = ?",
                (new_status, time.time() if new_status in ('confirmed', 'refunded', 'failed') else None, bundle_id),
            )
            conn.commit()
            conn.close()
            logger.debug(f"Inflight bundle status updated: {bundle_id[:12]} -> {new_status}")
        except Exception as e:
            logger.error(f"Failed to update inflight status: {e}")

    async def backup_database(self):
        """Create a backup of the database to prevent corruption."""
        try:
            os.makedirs("backups", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"backups/bot_history_{timestamp}.db"
            import sqlite3
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.execute(f"VACUUM INTO '{backup_path}'")
            conn.close()
            logger.info(f"Database backup created: {backup_path}")
        except Exception as e:
            logger.warning(f"Failed to backup database: {e}")

    async def start_batch_writer(self):
        self.running = True
        self.write_task = asyncio.create_task(self._batch_write_worker())
        shared_state.active_tasks.add(self.write_task)
        self.write_task.add_done_callback(shared_state.active_tasks.discard)
        logger.info("Data aggregator batch writer started")

    async def stop_batch_writer(self):
        """Stop the background batch writer task."""
        self.running = False
        if self.write_task:
            await self.write_task
        logger.info("Data aggregator batch writer stopped")

    async def _batch_write_worker(self):
        """Background worker that batches database writes."""
        batch = []
        batch_size = 50
        flush_interval = 5.0  # Flush every 5 seconds

        while self.running:
            try:
                # Wait for next item or timeout
                try:
                    item = await asyncio.wait_for(
                        self.write_queue.get(), timeout=flush_interval
                    )
                    batch.append(item)
                except asyncio.TimeoutError:
                    pass  # No items, check if we have batch to flush

                # Flush if batch is full or periodic flush
                if len(batch) >= batch_size or (
                    batch and time.time() - batch[0]["timestamp"] > flush_interval
                ):
                    await self._flush_batch(batch)
                    batch = []

            except Exception as e:
                logger.error(f"Batch write worker error: {e}")
                await asyncio.sleep(1)

        # Fix 64: Final flush on shutdown — completely drain the queue
        # to prevent data loss of pending events.
        while not self.write_queue.empty():
            try:
                item = self.write_queue.get_nowait()
                batch.append(item)
            except asyncio.QueueEmpty:
                break
        if batch:
            await self._flush_batch(batch)

    async def _flush_batch(self, batch: List[Dict]):
        """Flush a batch of items to database."""
        if not batch:
            return

        try:
            async with aiosqlite.connect(self.db_path, timeout=30) as db:
                await db.executemany(
                    """
                    INSERT INTO events
                    (timestamp, event_type, webhook_id, transaction_signature,
                     input_data, parsed_opportunity, simulation_result, execution_result, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    [
                        (
                            item["timestamp"],
                            item["event_type"],
                            item["webhook_id"],
                            item["transaction_signature"],
                            item["input_data"],
                            item["parsed_opportunity"],
                            item["simulation_result"],
                            item["execution_result"],
                            item["metadata"],
                        )
                        for item in batch
                    ],
                )
                await db.commit()

            logger.debug(f"Flushed {len(batch)} events to database")

        except Exception as e:
            logger.error(f"Batch flush failed: {e}")

    async def log_event(self, event_type: str, **kwargs):
        """Log an event asynchronously using persistent connection."""
        try:
            timestamp = time.time()
            data = {
                "timestamp": timestamp,
                "event_type": event_type,
                "webhook_id": kwargs.get("webhook_id"),
                "transaction_signature": kwargs.get("transaction_signature"),
                "input_data": orjson.dumps(
                    kwargs.get("input_data", {}), default=str
                ).decode(),
                "parsed_opportunity": orjson.dumps(
                    kwargs.get("parsed_opportunity", {}), default=str
                ).decode(),
                "simulation_result": orjson.dumps(
                    kwargs.get("simulation_result", {}), default=str
                ).decode(),
                "execution_result": orjson.dumps(
                    kwargs.get("execution_result", {}), default=str
                ).decode(),
                "metadata": orjson.dumps(
                    kwargs.get("metadata", {}), default=str
                ).decode(),
            }

            # Add to batch queue instead of direct DB write
            try:
                self.write_queue.put_nowait(data)
            except asyncio.QueueFull:
                logger.debug("Analytics queue full, dropping event to save memory.")

        except Exception as e:
            logger.warning(f"Failed to queue event {event_type}: {e}")

    # Specific logging methods for different event types
    async def log_webhook_event(self, webhook_id: str, input_data: Dict[str, Any]):
        """Log incoming webhook event."""
        await self.log_event(
            "HeliusWebhook", webhook_id=webhook_id, input_data=input_data
        )

    async def log_opportunity_found(
        self,
        webhook_id: str,
        parsed_opportunity: Dict[str, Any],
        metadata: Dict[str, Any] = None,
    ):
        """Log detected arbitrage opportunity."""
        # Add timestamp to metadata for better tracking
        enhanced_metadata = (metadata or {}).copy()
        enhanced_metadata["detection_timestamp"] = time.time()

        # Add arbitrage potential analysis if available
        if "arbitrage_potential" in parsed_opportunity:
            enhanced_metadata["arbitrage_potential"] = parsed_opportunity[
                "arbitrage_potential"
            ]

        await self.log_event(
            "OpportunityFound",
            webhook_id=webhook_id,
            parsed_opportunity=parsed_opportunity,
            metadata=enhanced_metadata,
        )

    async def log_opportunity_skipped(
        self, webhook_id: str, parsed_opportunity: Dict[str, Any], reason: str
    ):
        """Log skipped opportunity with reason."""
        metadata = {"skip_reason": reason}
        await self.log_event(
            "OpportunitySkipped",
            webhook_id=webhook_id,
            parsed_opportunity=parsed_opportunity,
            metadata=metadata,
        )

    async def log_simulation_start(
        self,
        webhook_id: str,
        transaction_signature: str,
        parsed_opportunity: Dict[str, Any],
    ):
        """Log simulation start."""
        await self.log_event(
            "SimulationStart",
            webhook_id=webhook_id,
            transaction_signature=transaction_signature,
            parsed_opportunity=parsed_opportunity,
        )

    async def log_simulation_result(
        self,
        webhook_id: str,
        transaction_signature: str,
        simulation_result: Dict[str, Any],
        metadata: Dict[str, Any] = None,
    ):
        """Log simulation result."""
        await self.log_event(
            "SimulationResult",
            webhook_id=webhook_id,
            transaction_signature=transaction_signature,
            simulation_result=simulation_result,
            metadata=metadata or {},
        )

    async def log_tx_sent(
        self,
        transaction_signature: str,
        execution_result: Dict[str, Any],
        metadata: Dict[str, Any] = None,
    ):
        """Log transaction sent."""
        await self.log_event(
            "TxSent",
            transaction_signature=transaction_signature,
            execution_result=execution_result,
            metadata=metadata or {},
        )

    async def log_tx_confirmed(
        self,
        transaction_signature: str,
        execution_result: Dict[str, Any],
        metadata: Dict[str, Any] = None,
    ):
        """Log transaction confirmation."""
        await self.log_event(
            "TxConfirmed",
            transaction_signature=transaction_signature,
            execution_result=execution_result,
            metadata=metadata or {},
        )

    async def log_tx_failed(
        self,
        transaction_signature: str,
        execution_result: Dict[str, Any],
        metadata: Dict[str, Any] = None,
    ):
        """Log transaction failure."""
        await self.log_event(
            "TxFailed",
            transaction_signature=transaction_signature,
            execution_result=execution_result,
            metadata=metadata or {},
        )

    async def cleanup_old_data(self, keep_hours: int = None):
        """Remove events older than keep_hours and archive aggregated stats.

        Reads DB_RETENTION_HOURS from .env (default 24 hours) to prevent phantom
        database growth and ghost errors from past runs.
        """
        if keep_hours is None:
            keep_hours = int(os.getenv("DB_RETENTION_HOURS", "24"))
        cutoff_timestamp = time.time() - (keep_hours * 60 * 60)

        async with aiosqlite.connect(self.db_path, timeout=30) as db:
            # Delete old events
            cursor = await db.execute(
                "DELETE FROM events WHERE timestamp < ?", (cutoff_timestamp,)
            )
            # Fix 63: Use cursor.rowcount instead of db.total_changes
            # total_changes is cumulative across all connections, rowcount is per-statement
            deleted_count = cursor.rowcount
            logger.info(f"Cleaned up {deleted_count} old events")

            # Update daily stats for the cleaned period
            await self._update_daily_stats(db)
            await db.commit()

    async def _update_daily_stats(self, db):
        """Update daily aggregated statistics."""
        # This is a simplified version - in practice you'd aggregate by day
        # For now, just update today's stats
        today = datetime.now().strftime("%Y-%m-%d")

        # Count events today
        cursor = await db.execute(
            """
            SELECT COUNT(*) FROM events
            WHERE date(timestamp, 'unixepoch') = ?
        """,
            (today,),
        )
        total_events = (await cursor.fetchone())[0]

        # Count opportunities
        cursor = await db.execute(
            """
            SELECT COUNT(*) FROM events
            WHERE date(timestamp, 'unixepoch') = ? AND event_type = 'OpportunityFound'
        """,
            (today,),
        )
        opportunities_found = (await cursor.fetchone())[0]

        # Count executions
        cursor = await db.execute(
            """
            SELECT COUNT(*) FROM events
            WHERE date(timestamp, 'unixepoch') = ? AND event_type = 'TxSent'
        """,
            (today,),
        )
        opportunities_executed = (await cursor.fetchone())[0]

        # Count successful trades
        cursor = await db.execute(
            """
            SELECT COUNT(*) FROM events
            WHERE date(timestamp, 'unixepoch') = ? AND event_type = 'TxConfirmed'
        """,
            (today,),
        )
        successful_trades = (await cursor.fetchone())[0]

        # Calculate total PNL
        cursor = await db.execute(
            """
            SELECT COALESCE(SUM(
                json_extract(execution_result, '$.real_profit_sol')
            ), 0) FROM events
            WHERE date(timestamp, 'unixepoch') = ? AND event_type = 'TxConfirmed'
        """,
            (today,),
        )
        total_pnl = (await cursor.fetchone())[0]

        # Update or insert daily stats
        await db.execute(
            """
            INSERT OR REPLACE INTO daily_stats
            (date, total_events, opportunities_found, opportunities_executed, successful_trades, total_pnl_sol)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                today,
                total_events,
                opportunities_found,
                opportunities_executed,
                successful_trades,
                total_pnl,
            ),
        )

    async def export_for_analysis(self, days: int = 7, output_file: str = None) -> str:
        """Export recent events to JSONL format for analysis."""
        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"bot_analysis_{timestamp}.jsonl"

        cutoff_timestamp = time.time() - (days * 24 * 60 * 60)

        async with aiosqlite.connect(self.db_path, timeout=30) as db:
            cursor = await db.execute(
                """
                SELECT * FROM events
                WHERE timestamp >= ?
                ORDER BY timestamp ASC
            """,
                (cutoff_timestamp,),
            )

            with open(output_file, "w") as f:
                async for row in cursor:
                    event_dict = {
                        "id": row[0],
                        "timestamp": row[1],
                        "event_type": row[2],
                        "webhook_id": row[3],
                        "transaction_signature": row[4],
                        "input_data": orjson.loads(row[5]) if row[5] else {},
                        "parsed_opportunity": orjson.loads(row[6]) if row[6] else {},
                        "simulation_result": orjson.loads(row[7]) if row[7] else {},
                        "execution_result": orjson.loads(row[8]) if row[8] else {},
                        "metadata": orjson.loads(row[9]) if row[9] else {},
                    }
                    f.write(orjson.dumps(event_dict).decode() + "\n")

        logger.info(f"Exported {days} days of data to {output_file}")
        return output_file

    # Analytics methods
    async def get_success_rate_by_pair(
        self, days: int = 7
    ) -> Dict[str, Dict[str, Any]]:
        """Get success rates for different LST pairs."""
        cutoff_timestamp = time.time() - (days * 24 * 60 * 60)

        async with aiosqlite.connect(self.db_path, timeout=30) as db:
            cursor = await db.execute(
                """
                SELECT
                    json_extract(parsed_opportunity, '$.pair') as pair,
                    COUNT(*) as total_found,
                    SUM(CASE WHEN event_type = 'TxConfirmed' THEN 1 ELSE 0 END) as successful,
                    AVG(json_extract(execution_result, '$.real_profit_sol')) as avg_profit
                FROM events
                WHERE timestamp >= ? AND event_type IN ('OpportunityFound', 'TxConfirmed')
                GROUP BY pair
                ORDER BY total_found DESC
            """,
                (cutoff_timestamp,),
            )

            results = {}
            async for row in cursor:
                pair = row[0] or "unknown"
                results[pair] = {
                    "total_found": row[1],
                    "successful": row[2],
                    "success_rate": row[2] / row[1] if row[1] > 0 else 0,
                    "avg_profit_sol": row[3] or 0,
                }

            return results

    async def get_execution_latency_stats(self, days: int = 7) -> Dict[str, float]:
        """Get average execution latency statistics."""
        cutoff_timestamp = time.time() - (days * 24 * 60 * 60)

        async with aiosqlite.connect(self.db_path, timeout=30) as db:
            cursor = await db.execute(
                """
                SELECT AVG(json_extract(metadata, '$.execution_time_ms')) as avg_latency
                FROM events
                WHERE timestamp >= ? AND event_type = 'TxSent'
            """,
                (cutoff_timestamp,),
            )

            row = await cursor.fetchone()
            return {"avg_execution_time_ms": row[0] or 0}

    async def get_top_routes(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get most profitable and frequent routes."""
        cutoff_timestamp = time.time() - (days * 24 * 60 * 60)

        async with aiosqlite.connect(self.db_path, timeout=30) as db:
            cursor = await db.execute(
                """
                SELECT
                    json_extract(parsed_opportunity, '$.route') as route,
                    COUNT(*) as frequency,
                    AVG(json_extract(execution_result, '$.real_profit_sol')) as avg_profit,
                    SUM(json_extract(execution_result, '$.real_profit_sol')) as total_profit
                FROM events
                WHERE timestamp >= ? AND event_type = 'TxConfirmed'
                GROUP BY route
                ORDER BY total_profit DESC
                LIMIT 10
            """,
                (cutoff_timestamp,),
            )

            results = []
            async for row in cursor:
                results.append(
                    {
                        "route": row[0] or "unknown",
                        "frequency": row[1],
                        "avg_profit_sol": row[2] or 0,
                        "total_profit_sol": row[3] or 0,
                    }
                )

            return results

    async def get_webhook_opportunity_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get statistics on webhook-detected opportunities."""
        cutoff_timestamp = time.time() - (days * 24 * 60 * 60)

        async with aiosqlite.connect(self.db_path, timeout=30) as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*) as total_webhook_events,
                       COUNT(CASE WHEN event_type = 'OpportunityFound' THEN 1 END) as opportunities_found,
                       COUNT(CASE WHEN event_type = 'OpportunitySkipped' THEN 1 END) as opportunities_skipped
                FROM events
                WHERE timestamp >= ? AND webhook_id IS NOT NULL
            """,
                (cutoff_timestamp,),
            )

            row = await cursor.fetchone()
            return {
                "total_webhook_events": row[0],
                "opportunities_found": row[1],
                "opportunities_skipped": row[2],
                "conversion_rate": row[1] / row[0] if row[0] > 0 else 0,
            }

    async def get_lst_arbitrage_opportunities(
        self, days: int = 7
    ) -> List[Dict[str, Any]]:
        """Get LST-specific arbitrage opportunities from webhooks."""
        cutoff_timestamp = time.time() - (days * 24 * 60 * 60)

        async with aiosqlite.connect(self.db_path, timeout=30) as db:
            cursor = await db.execute(
                """
                SELECT parsed_opportunity, metadata, timestamp
                FROM events
                WHERE timestamp >= ? AND event_type = 'OpportunityFound'
                      AND json_extract(parsed_opportunity, '$.type') = 'sanctum_lst_arbitrage'
                ORDER BY timestamp DESC
                LIMIT 50
            """,
                (cutoff_timestamp,),
            )

            results = []
            async for row in cursor:
                opportunity = orjson.loads(row[0]) if row[0] else {}
                metadata = orjson.loads(row[1]) if row[1] else {}
                results.append(
                    {
                        "opportunity": opportunity,
                        "metadata": metadata,
                        "timestamp": row[2],
                    }
                )

            return results

    async def get_skip_reasons(self, days: int = 7) -> Dict[str, int]:
        """Get reasons why opportunities were skipped."""
        cutoff_timestamp = time.time() - (days * 24 * 60 * 60)

        async with aiosqlite.connect(self.db_path, timeout=30) as db:
            cursor = await db.execute(
                """
                SELECT json_extract(metadata, '$.skip_reason') as reason, COUNT(*)
                FROM events
                WHERE timestamp >= ? AND event_type = 'OpportunitySkipped'
                GROUP BY reason
                ORDER BY COUNT(*) DESC
            """,
                (cutoff_timestamp,),
            )

            results = {}
            async for row in cursor:
                results[row[0] or "unknown"] = row[1]

            return results

    async def log_paper_trade(self, trade_data: Dict[str, Any]):
        """Log a paper trading transaction directly into the paper_trades table."""
        try:
            async with aiosqlite.connect(self.db_path, timeout=30) as db:
                await db.execute(
                    """
                    INSERT INTO paper_trades (
                        ts, slot, blockhash, route, token_in, token_out,
                        amount_lamports, gross_revenue_lamports, flashloan_fee_lamports,
                        dex_fee_lamports, slippage_bps, compute_cost_lamports,
                        network_fee_lamports, priority_fee_lamports, jito_tip_lamports,
                        ata_rent_lamports, total_cost_lamports, net_profit_lamports,
                        roi_pct, decision
                    ) VALUES (
                        datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                """,
                    (
                        trade_data.get("slot"),
                        trade_data.get("blockhash"),
                        trade_data.get("route"),
                        trade_data.get("token_in"),
                        trade_data.get("token_out"),
                        trade_data.get("amount_lamports"),
                        trade_data.get("gross_revenue_lamports"),
                        trade_data.get("flashloan_fee_lamports"),
                        trade_data.get("dex_fee_lamports"),
                        trade_data.get("slippage_bps"),
                        trade_data.get("compute_cost_lamports"),
                        trade_data.get("network_fee_lamports"),
                        trade_data.get("priority_fee_lamports"),
                        trade_data.get("jito_tip_lamports"),
                        trade_data.get("ata_rent_lamports"),
                        trade_data.get("total_cost_lamports"),
                        trade_data.get("net_profit_lamports"),
                        trade_data.get("roi_pct"),
                        trade_data.get("decision"),
                    ),
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to log paper trade: {e}")

    async def get_paper_trading_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get paper trading statistics from the normalized paper_trades table."""
        cutoff_timestamp = time.time() - (days * 24 * 60 * 60)

        async with aiosqlite.connect(self.db_path, timeout=30) as db:
            # Total paper trades
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM paper_trades
                WHERE ts >= datetime(?, 'unixepoch')
            """,
                (cutoff_timestamp,),
            )
            total_trades = (await cursor.fetchone())[0]

            # Total net profit
            cursor = await db.execute(
                """
                SELECT SUM(net_profit_lamports) FROM paper_trades
                WHERE ts >= datetime(?, 'unixepoch')
            """,
                (cutoff_timestamp,),
            )
            total_profit_lamports = (await cursor.fetchone())[0] or 0
            total_profit_sol = total_profit_lamports / 1e9

            # Most profitable routes
            cursor = await db.execute(
                """
                SELECT route, COUNT(*) as count, AVG(net_profit_lamports) as avg_profit_lamports
                FROM paper_trades
                WHERE ts >= datetime(?, 'unixepoch')
                GROUP BY route
                ORDER BY avg_profit_lamports DESC
                LIMIT 5
            """,
                (cutoff_timestamp,),
            )

            top_routes = []
            async for row in cursor:
                top_routes.append(
                    {
                        "route": row[0],
                        "count": row[1],
                        "avg_profit_sol": (row[2] or 0) / 1e9,
                    }
                )

            # Win rate
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM paper_trades
                WHERE ts >= datetime(?, 'unixepoch') AND net_profit_lamports > 0
            """,
                (cutoff_timestamp,),
            )
            wins = (await cursor.fetchone())[0]
            win_rate = wins / total_trades if total_trades > 0 else 0.0

            return {
                "total_trades": total_trades,
                "total_profit": total_profit_sol,
                "win_rate": win_rate,
                "top_routes": top_routes,
                "period_days": days,
            }
