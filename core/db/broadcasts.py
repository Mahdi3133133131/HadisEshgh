"""
پیگیری همگانی‌رسانی.

سند خواسته بود پیام به همهٔ کاربران برسد ولی نه یکباره، تا ربات
مسدود نشود. تلگرام روی هم‌رفته حدود سی پیام در ثانیه را برمی‌تابد؛
با فاصلهٔ پیش‌فرض پنجاه هزارم ثانیه، زیر آن سقف می‌مانیم.

پیشرفت در پایگاه داده نگه داشته می‌شود تا اگر ربات در میانهٔ کار
از پا افتاد، بدانیم تا کجا رفته است.
"""

from __future__ import annotations

import sqlite3

from core.db.database import execute, query_one


def create(admin_id: int, from_chat_id: int, from_msg_id: int, total: int) -> int:
    cursor = execute(
        """
        INSERT INTO broadcasts (admin_id, from_chat_id, from_msg_id, total, status)
        VALUES (?, ?, ?, ?, 'running')
        """,
        (admin_id, from_chat_id, from_msg_id, total),
    )
    return int(cursor.lastrowid)


def get(broadcast_id: int) -> sqlite3.Row | None:
    return query_one("SELECT * FROM broadcasts WHERE id = ?", (broadcast_id,))


def bump(broadcast_id: int, sent: int = 0, failed: int = 0) -> None:
    execute(
        "UPDATE broadcasts SET sent = sent + ?, failed = failed + ? WHERE id = ?",
        (sent, failed, broadcast_id),
    )


def finish(broadcast_id: int, status: str = "done") -> None:
    execute(
        "UPDATE broadcasts SET status = ?, finished_at = datetime('now') WHERE id = ?",
        (status, broadcast_id),
    )


def is_cancelled(broadcast_id: int) -> bool:
    """
    برای آنکه گرداننده بتواند همگانی‌رسانیِ درازِ در جریان را
    نیمه‌کاره بازایستاند.
    """
    row = query_one("SELECT status FROM broadcasts WHERE id = ?", (broadcast_id,))
    return bool(row) and row["status"] == "cancelled"


def cancel(broadcast_id: int) -> None:
    execute(
        "UPDATE broadcasts SET status = 'cancelled' WHERE id = ? AND status = 'running'",
        (broadcast_id,),
    )


def running() -> sqlite3.Row | None:
    """همگانی‌رسانیِ در جریان، اگر باشد — تا دو تا با هم آغاز نشوند."""
    return query_one(
        "SELECT * FROM broadcasts WHERE status = 'running' ORDER BY id DESC LIMIT 1"
    )
