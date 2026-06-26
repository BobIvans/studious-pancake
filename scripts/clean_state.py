#!/usr/bin/env python3
"""
Clean State Script - Wipe all persistent state before deployment.

This script clears:
1. Log files in logs/ folder (truncated, not deleted to preserve PM2 file handles)
2. All .jsonl files in the project root
 3. All tables in bot_history.db

 Usage: python scripts/clean_state.py
"""

import os
import glob
import sqlite3
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S"
)
logger = logging.getLogger("CleanState")


def truncate_logs():
    """Truncate log files in logs/ folder without deleting them."""
    logs_dir = Path("logs")
    log_files = ["bot-start.log", "pm2-out.log", "pm2-error.log"]

    for log_file in log_files:
        log_path = logs_dir / log_file
        if log_path.exists():
            try:
                log_path.write_text("")
                logger.info(f"🧹 Truncated: {log_file}")
            except Exception as e:
                logger.warning(f"Failed to truncate {log_file}: {e}")
        else:
            logger.debug(f"Skipped (not found): {log_file}")


def clean_jsonl_files():
    """Delete all .jsonl files in the project root."""
    project_root = Path(".")
    jsonl_files = list(project_root.glob("*.jsonl"))

    for jsonl_file in jsonl_files:
        try:
            jsonl_file.unlink()
            logger.info(f"🗑️ Removed: {jsonl_file.name}")
        except Exception as e:
            logger.warning(f"Failed to remove {jsonl_file}: {e}")


def clean_database(db_name: str):
    """Clear all tables in a SQLite database using DELETE + VACUUM."""
    db_path = Path(db_name)
    if not db_path.exists():
        logger.debug(f"Skipped (not found): {db_name}")
        return

    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()

        # Get all table names
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]

        # Disable foreign keys for deletion
        cursor.execute("PRAGMA foreign_keys=OFF;")

        for table in tables:
            cursor.execute(f"DELETE FROM {table};")
            logger.info(f"   Deleted table: {table}")

        # Re-enable foreign keys
        cursor.execute("PRAGMA foreign_keys=ON;")

        # Vacuum to reclaim disk space
        cursor.execute("VACUUM;")

        conn.commit()
        conn.close()
        logger.info(f"✅ Cleaned database: {db_name}")

    except Exception as e:
        logger.error(f"Failed to clean {db_name}: {e}")


def main():
    logger.info("🧹 Clean State Script - Starting full state wipe...")

    # 1. Truncate log files
    logger.info("\n📁 Step 1: Truncating log files...")
    truncate_logs()

    # 2. Clean .jsonl files
    logger.info("\n📄 Step 2: Removing .jsonl files...")
    clean_jsonl_files()

    # 3. Clean databases
    logger.info("\n🗄️ Step 3: Cleaning databases...")
    clean_database("bot_history.db")

    logger.info("\n✅ Clean State complete - Bot is ready for fresh deployment.")


if __name__ == "__main__":
    main()
