"""
پیام‌های **گذرای** ربات در گروه‌ها.

## چرا این هست

گروه‌ها با کار روزمرهٔ ربات شلوغ می‌شوند: گزارشِ هر ناکامی، کارتِ
داوریِ هر پیشکش، پیامِ وضعیت. کارِ هرکدام که تمام شد، ماندنشان
تنها شلوغی است — ولی ربات نشانی‌شان را نگه نمی‌داشت و راهی برای
برداشتنشان نبود.

## چرا تنها گذراها، و این نکته حیاتی است

در گروه بایگانی، پیام‌های ربات **همان نواهای بایگانی‌شده‌اند**.
اگر `/clean` هر چه ربات فرستاده را بردارد، بایگانی را نابود
می‌کند.

پس قاعده وارونه است: چیزی پاک می‌شود که **صریح** اینجا ثبت شده
باشد. نوایی که در گروه بایگانی می‌نشیند هرگز ثبت نمی‌شود، پس
هرگز برداشته نمی‌شود. فراموش کردنِ ثبت، به بی‌خطر بودن می‌انجامد
نه به فاجعه.
"""

from __future__ import annotations

import logging
import sqlite3

from core.db.database import execute, query_all, query_one

logger = logging.getLogger(__name__)


def remember(chat_id: int, message_id: int, kind: str = "") -> None:
    """
    نشانیِ یک پیامِ گذرا را نگه می‌دارد.

    ناکامی‌اش بالا نمی‌رود: نتوانستن در ثبتِ نشانی، دلیلی نیست که
    کارِ فراخوان بشکند. بدترین پیامدش این است که آن پیام دستی پاک
    شود.
    """
    if not chat_id or not message_id:
        return
    try:
        execute(
            """
            INSERT INTO bot_messages (chat_id, message_id, kind)
            VALUES (?, ?, ?)
            ON CONFLICT(chat_id, message_id) DO NOTHING
            """,
            (int(chat_id), int(message_id), kind or None),
        )
    except sqlite3.Error as exc:
        logger.debug("ثبت نشانیِ پیام گذرا نشد: %s", exc)


def pending(chat_id: int, limit: int = 200) -> list[sqlite3.Row]:
    """
    پیام‌های گذرای این گروه که هنوز برداشته نشده‌اند.

    از کهنه به تازه، چون کهنه‌ها بیشتر به درد نمی‌خورند — و اگر
    سقف بخورد، همان‌ها باید اول بروند.
    """
    return query_all(
        """
        SELECT message_id, kind, created_at
          FROM bot_messages
         WHERE chat_id = ?
         ORDER BY created_at
         LIMIT ?
        """,
        (int(chat_id), limit),
    )


def count(chat_id: int) -> int:
    row = query_one(
        "SELECT COUNT(*) AS c FROM bot_messages WHERE chat_id = ?", (int(chat_id),)
    )
    return int(row["c"]) if row else 0


def forget(chat_id: int, message_ids: list[int]) -> None:
    """نشانی‌هایی که دیگر لازم نیست — چه پاک شدند، چه نشد."""
    if not message_ids:
        return
    marks = ",".join("?" for _ in message_ids)
    execute(
        f"DELETE FROM bot_messages WHERE chat_id = ? AND message_id IN ({marks})",
        (int(chat_id), *[int(m) for m in message_ids]),
    )


def forget_all(chat_id: int) -> None:
    execute("DELETE FROM bot_messages WHERE chat_id = ?", (int(chat_id),))
