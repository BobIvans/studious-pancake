"""AI data collection utilities for arbitrage trade history."""

import csv
import asyncio
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

import aiosqlite


@dataclass
class ArbitrageTradeRecord:
    timestamp: float = field(default_factory=time.time)
    pair: str = ""
    initial_score: float = 0.0
    expected_profit_sol: float = 0.0
    actual_profit_sol: float = 0.0
    jito_tip_sol: float = 0.0
    execution_time_ms: float = 0.0
    result: str = "unknown"
    competitor_tip_sol: Optional[float] = None
    network_congestion: Optional[float] = None
    liquidity_depth_usd: Optional[float] = None
    slippage_realized: Optional[float] = None
    route: Optional[str] = None
    signature: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["datetime"] = datetime.fromtimestamp(self.timestamp).isoformat()
        return data


class AIDataCollector:
    """Collects arbitrage trade records into SQLite or CSV storage."""

    CSV_FIELDS = [
        "timestamp",
        "datetime",
        "pair",
        "initial_score",
        "expected_profit_sol",
        "actual_profit_sol",
        "jito_tip_sol",
        "execution_time_ms",
        "result",
        "competitor_tip_sol",
        "network_congestion",
        "liquidity_depth_usd",
        "slippage_realized",
        "route",
        "signature",
    ]

    def __init__(
        self,
        use_sqlite: bool = False,
        db_path: str = "ai_training_data.db",
        csv_path: str = "ai_training_data.csv",
    ):
        self.use_sqlite = use_sqlite
        self.db_path = db_path
        self.csv_path = csv_path
        self._records: deque = deque(maxlen=10000)

        if self.use_sqlite:
            self._init_sqlite()

    def _init_sqlite(self) -> None:
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS arbitrage_trades (
                    timestamp REAL PRIMARY KEY,
                    datetime TEXT NOT NULL,
                    pair TEXT,
                    initial_score REAL,
                    expected_profit_sol REAL,
                    actual_profit_sol REAL,
                    jito_tip_sol REAL,
                    execution_time_ms REAL,
                    result TEXT,
                    competitor_tip_sol REAL,
                    network_congestion REAL,
                    liquidity_depth_usd REAL,
                    slippage_realized REAL,
                    route TEXT,
                    signature TEXT
                )
                """
            )
            conn.commit()

    async def record_trade(self, record: Union[ArbitrageTradeRecord, Dict[str, Any]]) -> None:
        trade = self._normalize_record(record)
        self._records.append(trade)

        # deque(maxlen=10000) automatically drops oldest records — O(1), no pop(0) shift

        if self.use_sqlite:
            await self._insert_sqlite(trade)
        else:
            self._append_csv(trade)

    def _normalize_record(self, record: Union[ArbitrageTradeRecord, Dict[str, Any]]) -> Dict[str, Any]:
        if isinstance(record, ArbitrageTradeRecord):
            return record.to_dict()

        timestamp = float(record.get("timestamp", time.time()))
        data = {
            "timestamp": timestamp,
            "datetime": datetime.fromtimestamp(timestamp).isoformat(),
            "pair": record.get("pair", ""),
            "initial_score": float(record.get("initial_score", 0.0)),
            "expected_profit_sol": float(record.get("expected_profit_sol", 0.0)),
            "actual_profit_sol": float(record.get("actual_profit_sol", 0.0)),
            "jito_tip_sol": float(record.get("jito_tip_sol", 0.0)),
            "execution_time_ms": float(record.get("execution_time_ms", 0.0)),
            "result": record.get("result", "unknown"),
            "competitor_tip_sol": self._optional_float(record.get("competitor_tip_sol")),
            "network_congestion": self._optional_float(record.get("network_congestion")),
            "liquidity_depth_usd": self._optional_float(record.get("liquidity_depth_usd")),
            "slippage_realized": self._optional_float(record.get("slippage_realized")),
            "route": record.get("route"),
            "signature": record.get("signature"),
        }
        return data

    def _optional_float(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        return float(value)

    async def _insert_sqlite(self, trade: Dict[str, Any]) -> None:
        async with aiosqlite.connect(self.db_path, timeout=30) as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO arbitrage_trades (
                    timestamp, datetime, pair, initial_score, expected_profit_sol,
                    actual_profit_sol, jito_tip_sol, execution_time_ms, result,
                    competitor_tip_sol, network_congestion, liquidity_depth_usd,
                    slippage_realized, route, signature
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade["timestamp"],
                    trade["datetime"],
                    trade["pair"],
                    trade["initial_score"],
                    trade["expected_profit_sol"],
                    trade["actual_profit_sol"],
                    trade["jito_tip_sol"],
                    trade["execution_time_ms"],
                    trade["result"],
                    trade["competitor_tip_sol"],
                    trade["network_congestion"],
                    trade["liquidity_depth_usd"],
                    trade["slippage_realized"],
                    trade["route"],
                    trade["signature"],
                ),
            )
            await conn.commit()

    async def _load_sqlite_records(self) -> List[Dict[str, Any]]:
        if not Path(self.db_path).exists():
            return []
        async with aiosqlite.connect(self.db_path, timeout=30) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM arbitrage_trades ORDER BY timestamp DESC") as cursor:
                rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    def _append_csv(self, trade: Dict[str, Any]) -> None:
        path = Path(self.csv_path)
        write_header = not path.exists() or path.stat().st_size == 0
        with path.open("a", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=self.CSV_FIELDS)
            if write_header:
                writer.writeheader()
            writer.writerow({field: trade.get(field) for field in self.CSV_FIELDS})

    async def get_statistics(self) -> Dict[str, Any]:
        trades = self._records or await self._load_all_records()
        if not trades:
            return {
                "total_trades": 0,
                "success_rate": 0.0,
                "average_initial_score": 0.0,
                "average_actual_profit_sol": 0.0,
                "average_execution_time_ms": 0.0,
                "total_profit_sol": 0.0,
                "result_counts": {},
                "pair_counts": {},
            }

        successes = [trade for trade in trades if trade.get("result") == "success"]
        result_counts: Dict[str, int] = {}
        pair_counts: Dict[str, int] = {}
        for trade in trades:
            result = str(trade.get("result", "unknown"))
            pair = str(trade.get("pair", "unknown"))
            result_counts[result] = result_counts.get(result, 0) + 1
            pair_counts[pair] = pair_counts.get(pair, 0) + 1

        return {
            "total_trades": len(trades),
            "successful_trades": len(successes),
            "failed_trades": len(trades) - len(successes),
            "success_rate": len(successes) / len(trades),
            "average_initial_score": sum(float(t.get("initial_score", 0.0)) for t in trades) / len(trades),
            "average_actual_profit_sol": sum(float(t.get("actual_profit_sol", 0.0)) for t in trades) / len(trades),
            "average_execution_time_ms": sum(float(t.get("execution_time_ms", 0.0)) for t in trades) / len(trades),
            "total_profit_sol": sum(float(t.get("actual_profit_sol", 0.0)) for t in trades),
            "result_counts": result_counts,
            "pair_counts": pair_counts,
        }

    async def get_recent_trades(self, limit: int = 5) -> List[Dict[str, Any]]:
        trades = self._records or await self._load_all_records()
        return sorted(trades, key=lambda trade: float(trade.get("timestamp", 0.0)), reverse=True)[:limit]

    async def _load_all_records(self) -> List[Dict[str, Any]]:
        if self.use_sqlite:
            return await self._load_sqlite_records()
        return self._load_csv_records()

    async def _load_sqlite_records(self) -> List[Dict[str, Any]]:
        if not Path(self.db_path).exists():
            return []
        async with aiosqlite.connect(self.db_path, timeout=30) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM arbitrage_trades ORDER BY timestamp DESC") as cursor:
                rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    def _load_csv_records(self) -> List[Dict[str, Any]]:
        path = Path(self.csv_path)
        if not path.exists():
            return []
        with path.open(newline="") as file:
            return list(csv.DictReader(file))

    def export_for_analysis(self, days: int = 1) -> str:
        cutoff = time.time() - days * 86400
        trades = [trade for trade in self._records if float(trade.get("timestamp", 0.0)) >= cutoff]
        if not trades:
            trades = self._load_all_records()
            cutoff = time.time() - days * 86400
            trades = [trade for trade in trades if float(trade.get("timestamp", 0.0)) >= cutoff]

        export_path = Path(f"ai_training_export_{int(time.time())}.csv")
        with export_path.open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=self.CSV_FIELDS)
            writer.writeheader()
            for trade in trades:
                writer.writerow({field: trade.get(field) for field in self.CSV_FIELDS})
        return str(export_path)

    def clear(self) -> None:
        self._records.clear()
        if self.use_sqlite and Path(self.db_path).exists():
            Path(self.db_path).unlink()
            self._init_sqlite()
        csv_path = Path(self.csv_path)
        if csv_path.exists():
            csv_path.unlink()
