# -*- coding: utf-8 -*-
"""
نشستِ پذیرش — یکی برای هر گروه، نه برای هر گرداننده.

═══════════════════════════════════════════════════════════════
  چرا این هست
═══════════════════════════════════════════════════════════════

تا امروز وضعیتِ پذیرش در `context.user_data` می‌نشست، یعنی **برای
هر گرداننده جدا**. سه پیامد داشت:

۱. دو گرداننده در یک گروه، هم‌زمان دو جریان می‌راندند و
   صوت‌ها و پرسش‌ها و کارت‌هاشان در هم می‌رفت.

۲. گردانندهٔ B که کارتِ A را می‌نواخت، `user_data` **خودش**
   خوانده می‌شد؛ اگر جریانی نداشت پیامِ گمراه‌کنندهٔ «پذیرشی در
   جریان نیست» می‌گرفت و کارتِ A دست‌نخورده می‌ماند.

۳. و مهم‌تر: اگر نتِ گرداننده‌ای وسطِ کار قطع می‌شد، صفِ نیمه‌کاره
   در `user_data` او حبس می‌ماند و هیچ‌کس نمی‌توانست ادامه‌اش
   بدهد.

خواستهٔ کاربر روشن بود: «گردانندهٔ دیگر بتواند کار مرا ادامه دهد
یا کار خودش را آغاز کند؛ خودم هم که برگشتم ادامه دهم.» این یعنی
صف باید **مالِ گروه** باشد نه مالِ یک نفر.

═══════════════════════════════════════════════════════════════
  الگو
═══════════════════════════════════════════════════════════════

همان الگوی آزمودهٔ `feedbacks.try_acquire_lock` و
`searches.try_acquire_fill`: یک `UPDATE` اتمی با `expires_at`، و
تصمیم بر پایهٔ `rowcount`. دوباره‌نویسی‌اش یعنی روزی یکی درست شود
و دیگری نه.

`payload` همان `data`ی امروزی است، به JSON. نگه داشتنش در
دیتابیس یک سود دیگر هم دارد: راه‌اندازیِ دوبارهٔ ربات، صفِ
نیمه‌کاره را از بین نمی‌برد.
"""

from __future__ import annotations

import json
import logging
import sqlite3

from core.db.database import execute, query_one, transaction

logger = logging.getLogger(__name__)

# مهلتِ بی‌کنشی، به ثانیه.
#
# دو دقیقه، خواستهٔ خودِ کاربر: «وقتی از آخرین فعالیتش ۲ دقیقه
# بگذره قفل گروه باز می‌شه». هر کنشِ دارنده این را از نو می‌کِشد.
# ## چرا ده دقیقه، و نه دو
#
# دو دقیقه برای «قفل» بس بود ولی برای **کار** نه: نوشتنِ نامِ یک
# نوا با صفحه‌کلیدِ فارسی، آن هم وقتی گرداننده باید فایل را
# بشنود تا نامش را بداند، به‌آسانی از دو دقیقه می‌گذرد. مهلت که
# سر می‌رفت، ربات وسطِ کار اعلامِ «رها شد» می‌داد.
#
# اکنون هر کنش — نواختنِ دکمه **و نوشتنِ متن** — مهلت را نو
# می‌کند، پس این عدد تنها برای گردانندهٔ راستی غایب می‌ماند.
DEFAULT_TIMEOUT = 600


def ensure_table() -> None:
    """جدول را می‌سازد اگر نباشد. اجرای دوباره بی‌خطر است."""
    execute(
        """
        CREATE TABLE IF NOT EXISTS intake_sessions (
            chat_id     INTEGER PRIMARY KEY,
            owner_id    INTEGER,
            payload     TEXT NOT NULL DEFAULT '{}',
            expires_at  TEXT,
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def get(chat_id: int) -> sqlite3.Row | None:
    return query_one(
        "SELECT * FROM intake_sessions WHERE chat_id = ?", (int(chat_id),)
    )


def holder(chat_id: int) -> int | None:
    """
    گردانندهٔ دارندهٔ قفل، یا None اگر آزاد باشد.

    مهلتِ گذشته، آزاد شمرده می‌شود — همان جایی که گردانندهٔ دیگر
    می‌تواند کار را به دست بگیرد.
    """
    row = query_one(
        """
        SELECT owner_id FROM intake_sessions
         WHERE chat_id = ?
           AND owner_id IS NOT NULL
           AND expires_at IS NOT NULL
           AND expires_at > datetime('now')
        """,
        (int(chat_id),),
    )
    return int(row["owner_id"]) if row and row["owner_id"] is not None else None


def try_take(
    chat_id: int, admin_id: int, timeout_seconds: int = DEFAULT_TIMEOUT
) -> bool:
    """
    می‌کوشد قفلِ این گروه را برای این گرداننده بگیرد.

    گرفته می‌شود اگر: کسی نگرفته باشد، یا همین گرداننده پیش‌تر
    گرفته باشد (تا دنبالهٔ کارِ خودش را بگیرد)، یا مهلتِ دارندهٔ
    پیشین گذشته باشد.

    ردیف اگر نباشد ساخته می‌شود — آغازِ یک دستهٔ تازه.
    """
    # نشانهٔ بازه با علامتِ صریح ساخته می‌شود. اگر «+-120 seconds»
    # به SQLite برسد نمی‌شناسدش و به جای تاریخ NULL می‌دهد — و
    # ردیفی با مهلتِ NULL دیگر هرگز آزاد نمی‌شود.
    modifier = f"{int(timeout_seconds):+d} seconds"

    with transaction() as conn:
        cursor = conn.execute(
            """
            UPDATE intake_sessions
               SET owner_id   = ?,
                   expires_at = datetime('now', ?),
                   updated_at = datetime('now')
             WHERE chat_id = ?
               AND (
                     owner_id IS NULL
                  OR owner_id = ?
                  OR expires_at IS NULL
                  OR expires_at < datetime('now')
               )
            """,
            (int(admin_id), modifier, int(chat_id), int(admin_id)),
        )
        if cursor.rowcount > 0:
            return True

        # ردیفی نبود؟ پس این آغازِ کار است.
        existing = conn.execute(
            "SELECT 1 FROM intake_sessions WHERE chat_id = ?", (int(chat_id),)
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO intake_sessions (chat_id, owner_id, expires_at)
                VALUES (?, ?, datetime('now', ?))
                """,
                (int(chat_id), int(admin_id), modifier),
            )
            return True

    # ردیف بود و دستِ کسِ دیگری است که مهلتش نگذشته.
    return False


def touch(chat_id: int, timeout_seconds: int = DEFAULT_TIMEOUT) -> None:
    """مهلت را از نو می‌کِشد — پس از هر کنشِ دارنده."""
    modifier = f"{int(timeout_seconds):+d} seconds"
    execute(
        "UPDATE intake_sessions"
        " SET expires_at = datetime('now', ?), updated_at = datetime('now')"
        " WHERE chat_id = ?",
        (modifier, int(chat_id)),
    )


def save(chat_id: int, payload: dict) -> None:
    """
    وضعیتِ جریان را می‌نشاند.

    ناکامیِ سریال‌سازی خاموش نمی‌گذرد ولی کار را هم نمی‌شکند:
    نشستِ ذخیره‌نشده یعنی تحویلِ کار به گردانندهٔ دیگر شدنی نیست،
    و آن از ایستادنِ پذیرش بهتر است.
    """
    try:
        blob = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        logger.warning("وضعیتِ پذیرش سریال نشد: %s", exc)
        return
    execute(
        """
        INSERT INTO intake_sessions (chat_id, payload)
        VALUES (?, ?)
        ON CONFLICT(chat_id) DO UPDATE
           SET payload = excluded.payload, updated_at = datetime('now')
        """,
        (int(chat_id), blob),
    )


def load(chat_id: int) -> dict | None:
    """وضعیتِ جریان، یا None اگر نشستی نباشد."""
    row = get(chat_id)
    if row is None or not row["payload"]:
        return None
    try:
        data = json.loads(row["payload"])
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) and data else None


def clear(chat_id: int) -> None:
    """نشست را می‌بندد — پایانِ کار یا رهاکردنش."""
    execute("DELETE FROM intake_sessions WHERE chat_id = ?", (int(chat_id),))


def expired(within_seconds: int = 0) -> list[sqlite3.Row]:
    """
    نشست‌هایی که مهلتشان گذشته ولی هنوز کارِ نیمه‌کاره دارند.

    کارِ دوره‌ای با این می‌فهمد کجا باید اعلام کند «قفل باز شد؛
    هر گرداننده‌ای می‌تواند ادامه دهد».
    """
    from core.db.database import query_all

    return query_all(
        """
        SELECT * FROM intake_sessions
         WHERE owner_id IS NOT NULL
           AND expires_at IS NOT NULL
           AND expires_at < datetime('now')
        """
    )


def release(chat_id: int) -> None:
    """
    قفل را آزاد می‌کند ولی صف را نگه می‌دارد.

    این همان لحظه‌ای است که مهلت گذشته: کار نیمه‌کاره سرِ جایش
    می‌ماند تا هر گرداننده‌ای — از جمله خودِ آغازگر — دنباله‌اش را
    بگیرد.
    """
    execute(
        "UPDATE intake_sessions SET owner_id = NULL, expires_at = NULL"
        " WHERE chat_id = ?",
        (int(chat_id),),
    )
