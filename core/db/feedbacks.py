"""
نقد و انتقادات کاربران، همراه با قفل پاسخ‌گویی.

سند خواسته بود وقتی گرداننده‌ای بر «پاسخ‌گویی» می‌نوازد، دیگران
نتوانند همان پیام را پاسخ دهند. دو نکته که در سند نیامده بود و
اینجا افزوده شده:

۱) قفل با یک دستور اتمی گرفته می‌شود، نه با خواندن و سپس نوشتن.
   اگر دو گرداننده در یک لحظه بنوازند، در حالت خواندن-سپس-نوشتن
   هر دو قفل را می‌گیرند؛ در این شکل تنها یکی کامیاب می‌شود.

۲) قفل مهلت دارد. اگر گرداننده‌ای دکمه را بزند و کار را رها کند،
   بی مهلت، آن انتقاد برای همیشه بی‌پاسخ می‌ماند.
"""

from __future__ import annotations

import sqlite3

from core.db.database import execute, query_all, query_one, transaction


def create(
    user_id: int,
    content_kind: str,
    content_text: str | None = None,
    file_id: str | None = None,
) -> int:
    cursor = execute(
        """
        INSERT INTO feedbacks (user_id, content_kind, content_text, file_id)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, content_kind, content_text, file_id),
    )
    return int(cursor.lastrowid)


def get(feedback_id: int) -> sqlite3.Row | None:
    return query_one("SELECT * FROM feedbacks WHERE id = ?", (feedback_id,))


def set_group_message(feedback_id: int, message_id: int) -> None:
    execute(
        "UPDATE feedbacks SET group_msg_id = ? WHERE id = ?",
        (message_id, feedback_id),
    )


def try_acquire_lock(
    feedback_id: int, admin_id: int, timeout_seconds: int
) -> tuple[bool, sqlite3.Row | None]:
    """
    می‌کوشد قفل پاسخ‌گویی را برای این گرداننده بگیرد.

    قفل گرفته می‌شود اگر: کسی آن را نگرفته باشد، یا همین گرداننده
    پیش‌تر گرفته باشد (تا بتواند دنبالهٔ کار خود را بگیرد)، یا مهلت
    قفل پیشین گذشته باشد.

    بازگشتی: (آیا گرفته شد، رکورد تازه)
    """
    # نشانهٔ بازه با علامت صریح ساخته می‌شود. اگر «+-5 seconds»
    # به SQLite برسد، آن را نمی‌شناسد و به جای تاریخ، NULL می‌دهد —
    # و ردیفی با مهلت NULL دیگر هرگز آزاد نمی‌شود.
    modifier = f"{int(timeout_seconds):+d} seconds"

    with transaction() as conn:
        cursor = conn.execute(
            """
            UPDATE feedbacks
               SET lock_admin_id   = ?,
                   lock_expires_at = datetime('now', ?),
                   status          = 'answering'
             WHERE id = ?
               AND status != 'answered'
               AND (
                     lock_admin_id IS NULL
                  OR lock_admin_id = ?
                  OR lock_expires_at IS NULL
                  OR lock_expires_at < datetime('now')
               )
            """,
            (admin_id, modifier, feedback_id, admin_id),
        )
        acquired = cursor.rowcount > 0

    return acquired, get(feedback_id)


def release_lock(feedback_id: int, admin_id: int | None = None) -> bool:
    """
    قفل را رها می‌کند و انتقاد را به حالت گشوده بازمی‌گرداند.

    اگر admin_id داده شود، تنها همان دارندهٔ قفل می‌تواند رهایش کند.
    """
    sql = """
        UPDATE feedbacks
           SET lock_admin_id = NULL, lock_expires_at = NULL, status = 'open'
         WHERE id = ? AND status = 'answering'
    """
    params: list[object] = [feedback_id]
    if admin_id is not None:
        sql += " AND lock_admin_id = ?"
        params.append(admin_id)

    cursor = execute(sql, params)
    return cursor.rowcount > 0


def mark_answered(feedback_id: int, admin_id: int) -> bool:
    """
    انتقاد را پاسخ‌داده‌شده نشان می‌کند و قفل را برمی‌دارد.

    بازگشتی: آیا همین فراخوان وضعیت را دگرگون کرد. اگر پیش‌تر
    پاسخ داده شده باشد False برمی‌گردد و کاربر دو بار آگاه نمی‌شود.
    """
    cursor = execute(
        """
        UPDATE feedbacks
           SET status = 'answered',
               answered_by = ?,
               answered_at = datetime('now'),
               lock_admin_id = NULL,
               lock_expires_at = NULL
         WHERE id = ? AND status != 'answered'
        """,
        (admin_id, feedback_id),
    )
    return cursor.rowcount > 0


def current_lock_holder(feedback_id: int) -> int | None:
    """
    شناسهٔ گرداننده‌ای که هم‌اکنون قفل را در دست دارد، یا None.

    قفلِ مهلت‌گذشته، بی‌دارنده شمرده می‌شود.
    """
    row = query_one(
        """
        SELECT lock_admin_id FROM feedbacks
         WHERE id = ?
           AND status = 'answering'
           AND lock_expires_at > datetime('now')
        """,
        (feedback_id,),
    )
    return int(row["lock_admin_id"]) if row and row["lock_admin_id"] else None


def open_count() -> int:
    row = query_one("SELECT COUNT(*) AS c FROM feedbacks WHERE status != 'answered'")
    return int(row["c"]) if row else 0


def by_user(user_id: int, limit: int = 20) -> list[sqlite3.Row]:
    return query_all(
        "SELECT * FROM feedbacks WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    )
