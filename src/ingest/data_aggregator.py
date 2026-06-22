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
        cursor.execute("PRAGMA cache_size=1000;")
        cursor.execute("PRAGMA temp_store=MEMORY;")

        # Main events table
        cursor.execute('''
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
        ''')

        # Aggregated stats table for historical data
        cursor.execute('''
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
        ''')

        # Create indexes for performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON events(timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_event_type ON events(event_type)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_webhook_id ON events(webhook_id)')

        conn.commit()
        conn.close()

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
                    item = await asyncio.wait_for(self.write_queue.get(), timeout=flush_interval)
                    batch.append(item)
                except asyncio.TimeoutError:
                    pass  # No items, check if we have batch to flush

                # Flush if batch is full or periodic flush
                if len(batch) >= batch_size or (batch and time.time() - batch[0]['timestamp'] > flush_interval):
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
                await db.executemany('''
                    INSERT INTO events
                    (timestamp, event_type, webhook_id, transaction_signature,
                     input_data, parsed_opportunity, simulation_result, execution_result, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', [(item['timestamp'], item['event_type'], item['webhook_id'],
                       item['transaction_signature'], item['input_data'], item['parsed_opportunity'],
                       item['simulation_result'], item['execution_result'], item['metadata']) for item in batch])
                await db.commit()

            logger.debug(f"Flushed {len(batch)} events to database")

        except Exception as e:
            logger.error(f"Batch flush failed: {e}")

    async def log_event(self, event_type: str, **kwargs):
        """Log an event asynchronously using persistent connection."""
        try:
            timestamp = time.time()
            data = {
                'timestamp': timestamp,
                'event_type': event_type,
                'webhook_id': kwargs.get('webhook_id'),
                'transaction_signature': kwargs.get('transaction_signature'),
                'input_data': orjson.dumps(kwargs.get('input_data', {}), default=str).decode(),
                'parsed_opportunity': orjson.dumps(kwargs.get('parsed_opportunity', {}), default=str).decode(),
                'simulation_result': orjson.dumps(kwargs.get('simulation_result', {}), default=str).decode(),
                'execution_result': orjson.dumps(kwargs.get('execution_result', {}), default=str).decode(),
                'metadata': orjson.dumps(kwargs.get('metadata', {}), default=str).decode()
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
        await self.log_event('HeliusWebhook', webhook_id=webhook_id, input_data=input_data)

    async def log_opportunity_found(self, webhook_id: str, parsed_opportunity: Dict[str, Any], metadata: Dict[str, Any] = None):
        """Log detected arbitrage opportunity."""
        # Add timestamp to metadata for better tracking
        enhanced_metadata = (metadata or {}).copy()
        enhanced_metadata['detection_timestamp'] = time.time()

        # Add arbitrage potential analysis if available
        if 'arbitrage_potential' in parsed_opportunity:
            enhanced_metadata['arbitrage_potential'] = parsed_opportunity['arbitrage_potential']

        await self.log_event('OpportunityFound', webhook_id=webhook_id,
                           parsed_opportunity=parsed_opportunity, metadata=enhanced_metadata)

    async def log_opportunity_skipped(self, webhook_id: str, parsed_opportunity: Dict[str, Any], reason: str):
        """Log skipped opportunity with reason."""
        metadata = {'skip_reason': reason}
        await self.log_event('OpportunitySkipped', webhook_id=webhook_id,
                           parsed_opportunity=parsed_opportunity, metadata=metadata)

    async def log_simulation_start(self, webhook_id: str, transaction_signature: str, parsed_opportunity: Dict[str, Any]):
        """Log simulation start."""
        await self.log_event('SimulationStart', webhook_id=webhook_id,
                           transaction_signature=transaction_signature, parsed_opportunity=parsed_opportunity)

    async def log_simulation_result(self, webhook_id: str, transaction_signature: str,
                                  simulation_result: Dict[str, Any], metadata: Dict[str, Any] = None):
        """Log simulation result."""
        await self.log_event('SimulationResult', webhook_id=webhook_id,
                           transaction_signature=transaction_signature,
                           simulation_result=simulation_result, metadata=metadata or {})

    async def log_tx_sent(self, transaction_signature: str, execution_result: Dict[str, Any], metadata: Dict[str, Any] = None):
        """Log transaction sent."""
        await self.log_event('TxSent', transaction_signature=transaction_signature,
                           execution_result=execution_result, metadata=metadata or {})

    async def log_tx_confirmed(self, transaction_signature: str, execution_result: Dict[str, Any], metadata: Dict[str, Any] = None):
        """Log transaction confirmation."""
        await self.log_event('TxConfirmed', transaction_signature=transaction_signature,
                           execution_result=execution_result, metadata=metadata or {})

    async def log_tx_failed(self, transaction_signature: str, execution_result: Dict[str, Any], metadata: Dict[str, Any] = None):
        """Log transaction failure."""
        await self.log_event('TxFailed', transaction_signature=transaction_signature,
                           execution_result=execution_result, metadata=metadata or {})

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
            await db.execute('DELETE FROM events WHERE timestamp < ?', (cutoff_timestamp,))
            deleted_count = db.total_changes
            logger.info(f"Cleaned up {deleted_count} old events")

            # Update daily stats for the cleaned period
            await self._update_daily_stats(db)
            await db.commit()

    async def _update_daily_stats(self, db):
        """Update daily aggregated statistics."""
        # This is a simplified version - in practice you'd aggregate by day
        # For now, just update today's stats
        today = datetime.now().strftime('%Y-%m-%d')

        # Count events today
        cursor = await db.execute('''
            SELECT COUNT(*) FROM events
            WHERE date(timestamp, 'unixepoch') = ?
        ''', (today,))
        total_events = (await cursor.fetchone())[0]

        # Count opportunities
        cursor = await db.execute('''
            SELECT COUNT(*) FROM events
            WHERE date(timestamp, 'unixepoch') = ? AND event_type = 'OpportunityFound'
        ''', (today,))
        opportunities_found = (await cursor.fetchone())[0]

        # Count executions
        cursor = await db.execute('''
            SELECT COUNT(*) FROM events
            WHERE date(timestamp, 'unixepoch') = ? AND event_type = 'TxSent'
        ''', (today,))
        opportunities_executed = (await cursor.fetchone())[0]

        # Count successful trades
        cursor = await db.execute('''
            SELECT COUNT(*) FROM events
            WHERE date(timestamp, 'unixepoch') = ? AND event_type = 'TxConfirmed'
        ''', (today,))
        successful_trades = (await cursor.fetchone())[0]

        # Calculate total PNL
        cursor = await db.execute('''
            SELECT COALESCE(SUM(
                json_extract(execution_result, '$.real_profit_sol')
            ), 0) FROM events
            WHERE date(timestamp, 'unixepoch') = ? AND event_type = 'TxConfirmed'
        ''', (today,))
        total_pnl = (await cursor.fetchone())[0]

        # Update or insert daily stats
        await db.execute('''
            INSERT OR REPLACE INTO daily_stats
            (date, total_events, opportunities_found, opportunities_executed, successful_trades, total_pnl_sol)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (today, total_events, opportunities_found, opportunities_executed, successful_trades, total_pnl))

    async def export_for_analysis(self, days: int = 7, output_file: str = None) -> str:
        """Export recent events to JSONL format for analysis."""
        if output_file is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = f"bot_analysis_{timestamp}.jsonl"

        cutoff_timestamp = time.time() - (days * 24 * 60 * 60)

        async with aiosqlite.connect(self.db_path, timeout=30) as db:
            cursor = await db.execute('''
                SELECT * FROM events
                WHERE timestamp >= ?
                ORDER BY timestamp ASC
            ''', (cutoff_timestamp,))

            with open(output_file, 'w') as f:
                async for row in cursor:
                    event_dict = {
                        'id': row[0],
                        'timestamp': row[1],
                        'event_type': row[2],
                        'webhook_id': row[3],
                        'transaction_signature': row[4],
                        'input_data': orjson.loads(row[5]) if row[5] else {},
                        'parsed_opportunity': orjson.loads(row[6]) if row[6] else {},
                        'simulation_result': orjson.loads(row[7]) if row[7] else {},
                        'execution_result': orjson.loads(row[8]) if row[8] else {},
                        'metadata': orjson.loads(row[9]) if row[9] else {}
                    }
                    f.write(orjson.dumps(event_dict).decode() + '\n')

        logger.info(f"Exported {days} days of data to {output_file}")
        return output_file

    # Analytics methods
    async def get_success_rate_by_pair(self, days: int = 7) -> Dict[str, Dict[str, Any]]:
        """Get success rates for different LST pairs."""
        cutoff_timestamp = time.time() - (days * 24 * 60 * 60)

        async with aiosqlite.connect(self.db_path, timeout=30) as db:
            cursor = await db.execute('''
                SELECT
                    json_extract(parsed_opportunity, '$.pair') as pair,
                    COUNT(*) as total_found,
                    SUM(CASE WHEN event_type = 'TxConfirmed' THEN 1 ELSE 0 END) as successful,
                    AVG(json_extract(execution_result, '$.real_profit_sol')) as avg_profit
                FROM events
                WHERE timestamp >= ? AND event_type IN ('OpportunityFound', 'TxConfirmed')
                GROUP BY pair
                ORDER BY total_found DESC
            ''', (cutoff_timestamp,))

            results = {}
            async for row in cursor:
                pair = row[0] or 'unknown'
                results[pair] = {
                    'total_found': row[1],
                    'successful': row[2],
                    'success_rate': row[2] / row[1] if row[1] > 0 else 0,
                    'avg_profit_sol': row[3] or 0
                }

            return results

    async def get_execution_latency_stats(self, days: int = 7) -> Dict[str, float]:
        """Get average execution latency statistics."""
        cutoff_timestamp = time.time() - (days * 24 * 60 * 60)

        async with aiosqlite.connect(self.db_path, timeout=30) as db:
            cursor = await db.execute('''
                SELECT AVG(json_extract(metadata, '$.execution_time_ms')) as avg_latency
                FROM events
                WHERE timestamp >= ? AND event_type = 'TxSent'
            ''', (cutoff_timestamp,))

            row = await cursor.fetchone()
            return {'avg_execution_time_ms': row[0] or 0}

    async def get_top_routes(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get most profitable and frequent routes."""
        cutoff_timestamp = time.time() - (days * 24 * 60 * 60)

        async with aiosqlite.connect(self.db_path, timeout=30) as db:
            cursor = await db.execute('''
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
            ''', (cutoff_timestamp,))

            results = []
            async for row in cursor:
                results.append({
                    'route': row[0] or 'unknown',
                    'frequency': row[1],
                    'avg_profit_sol': row[2] or 0,
                    'total_profit_sol': row[3] or 0
                })

            return results

    async def get_webhook_opportunity_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get statistics on webhook-detected opportunities."""
        cutoff_timestamp = time.time() - (days * 24 * 60 * 60)

        async with aiosqlite.connect(self.db_path, timeout=30) as db:
            cursor = await db.execute('''
                SELECT COUNT(*) as total_webhook_events,
                       COUNT(CASE WHEN event_type = 'OpportunityFound' THEN 1 END) as opportunities_found,
                       COUNT(CASE WHEN event_type = 'OpportunitySkipped' THEN 1 END) as opportunities_skipped
                FROM events
                WHERE timestamp >= ? AND webhook_id IS NOT NULL
            ''', (cutoff_timestamp,))

            row = await cursor.fetchone()
            return {
                'total_webhook_events': row[0],
                'opportunities_found': row[1],
                'opportunities_skipped': row[2],
                'conversion_rate': row[1] / row[0] if row[0] > 0 else 0
            }

    async def get_lst_arbitrage_opportunities(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get LST-specific arbitrage opportunities from webhooks."""
        cutoff_timestamp = time.time() - (days * 24 * 60 * 60)

        async with aiosqlite.connect(self.db_path, timeout=30) as db:
            cursor = await db.execute('''
                SELECT parsed_opportunity, metadata, timestamp
                FROM events
                WHERE timestamp >= ? AND event_type = 'OpportunityFound'
                      AND json_extract(parsed_opportunity, '$.type') = 'sanctum_lst_arbitrage'
                ORDER BY timestamp DESC
                LIMIT 50
            ''', (cutoff_timestamp,))

            results = []
            async for row in cursor:
                opportunity = orjson.loads(row[0]) if row[0] else {}
                metadata = orjson.loads(row[1]) if row[1] else {}
                results.append({
                    'opportunity': opportunity,
                    'metadata': metadata,
                    'timestamp': row[2]
                })

            return results

    async def get_skip_reasons(self, days: int = 7) -> Dict[str, int]:
        """Get reasons why opportunities were skipped."""
        cutoff_timestamp = time.time() - (days * 24 * 60 * 60)

        async with aiosqlite.connect(self.db_path, timeout=30) as db:
            cursor = await db.execute('''
                SELECT json_extract(metadata, '$.skip_reason') as reason, COUNT(*)
                FROM events
                WHERE timestamp >= ? AND event_type = 'OpportunitySkipped'
                GROUP BY reason
                ORDER BY COUNT(*) DESC
            ''', (cutoff_timestamp,))

            results = {}
            async for row in cursor:
                results[row[0] or 'unknown'] = row[1]

            return results

    async def log_paper_trade(self, trade_data: Dict[str, Any]):
        """Log a paper trading transaction to the database via non-blocking write queue."""
        try:
            input_data = {
                'route': trade_data.get('route'),
                'token_in': trade_data.get('token_in'),
                'token_out': trade_data.get('token_out'),
                'amount': trade_data.get('amount')
            }
            execution_result = {
                'profit': trade_data.get('actual_profit'),
                'balance_after': trade_data.get('balance_after')
            }
            metadata = {
                'paper_trading': True,
                'dex_pair': trade_data.get('dex_pair'),
                'confidence': trade_data.get('confidence')
            }
            
            await self.log_event(
                'PaperTrade',
                transaction_signature=trade_data.get('trade_id', 'unknown'),
                input_data=input_data,
                execution_result=execution_result,
                metadata=metadata
            )

        except Exception as e:
            logger.error(f"Failed to queue paper trade: {e}")

    async def get_paper_trading_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get paper trading statistics."""
        cutoff_timestamp = time.time() - (days * 24 * 60 * 60)

        async with aiosqlite.connect(self.db_path) as db:
            # Total paper trades
            cursor = await db.execute('''
                SELECT COUNT(*) FROM events
                WHERE timestamp >= ? AND event_type = 'PaperTrade'
            ''', (cutoff_timestamp,))
            total_trades = (await cursor.fetchone())[0]

            # Total profit
            cursor = await db.execute('''
                SELECT SUM(CAST(json_extract(execution_result, '$.profit') AS REAL))
                FROM events
                WHERE timestamp >= ? AND event_type = 'PaperTrade'
            ''', (cutoff_timestamp,))
            total_profit = (await cursor.fetchone())[0] or 0.0

            # Most profitable routes
            cursor = await db.execute('''
                SELECT json_extract(input_data, '$.route') as route,
                       COUNT(*) as count,
                       AVG(CAST(json_extract(execution_result, '$.profit') AS REAL)) as avg_profit
                FROM events
                WHERE timestamp >= ? AND event_type = 'PaperTrade'
                GROUP BY route
                ORDER BY avg_profit DESC
                LIMIT 5
            ''', (cutoff_timestamp,))

            top_routes = []
            async for row in cursor:
                top_routes.append({
                    'route': row[0],
                    'count': row[1],
                    'avg_profit': row[2]
                })

            return {
                'total_trades': total_trades,
                'total_profit': total_profit,
                'top_routes': top_routes,
                'period_days': days
            }