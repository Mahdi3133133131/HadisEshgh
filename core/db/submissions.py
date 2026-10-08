"""
پیشکش‌های کاربران — نواهایی که برای افزوده شدن به گنجینه فرستاده می‌شوند.

چرخهٔ کار: کاربر نوا می‌فرستد ← نام مداح و سبک پرسیده می‌شود ←
در گروه گردانندگان با دکمهٔ تأیید/رد نمایان می‌گردد ← با تأیید،
نوا به گنجینه می‌رود و سکه‌ای به پیشکش‌کننده بازمی‌گردد.

نکتهٔ نگهبانی: پیش از تأیید، تکراری بودن سنجیده می‌شود. بی این سنجش،
کسی می‌توانست نوایی را که خودِ ربات به او داده دگربار بفرستد و
بی‌پایان سکه بستاند.
"""

from __future__ import annotations

import sqlite3

from core.db.database import execute, query_all, query_one, transaction


def create(
    user_id: int,
    file_id: str,
    file_unique_id: str | None = None,
    file_name: str | None = None,
    duration: int | None = None,
    sha256: str | None = None,
    origin_search_id: int | None = None,
) -> int:
    cursor = execute(
        """
        INSERT INTO submissions (
            user_id, file_id, file_unique_id, file_name, duration, sha256, origin_search_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, file_id, file_unique_id, file_name, duration, sha256, origin_search_id),
    )
    return int(cursor.lastrowid)


def get(submission_id: int) -> sqlite3.Row | None:
    return query_one("SELECT * FROM submissions WHERE id = ?", (submission_id,))


def set_details(
    submission_id: int,
    madah: str | None,
    style: str | None,
    title: str | None = None,
) -> None:
    execute(
        "UPDATE submissions SET madah = ?, style = ?, title = ? WHERE id = ? ",
        (madah, style, title, submission_id),
    )


# بخش‌هایی که ویرایش‌پذیرند. فهرست سفید است نه سیاه: نام ستون
# یک‌راست در SQL می‌نشیند و هر چیز دیگری، راهِ تزریق می‌شد.
EDITABLE = ("madah", "style", "title")


def set_field(submission_id: int, field: str, value: str) -> bool:
    """
    یک بخش از پیشکش را دگرگون می‌کند.

    بازگشتی: آیا چیزی دگرگون شد.
    """
    if field not in EDITABLE:
        raise ValueError(f"بخش «{field}» ویرایش‌پذیر نیست.")
    cursor = execute(
        f"UPDATE submissions SET {field} = ? WHERE id = ?", (value, submission_id)
    )
    return cursor.rowcount > 0


def set_group_message(submission_id: int, message_id: int) -> None:
    execute(
        "UPDATE submissions SET group_msg_id = ? WHERE id = ?",
        (message_id, submission_id),
    )


def mark_duplicate(submission_id: int, track_id: int) -> None:
    execute(
        """
        UPDATE submissions
           SET status = 'duplicate', is_duplicate_of = ?, reviewed_at = datetime('now')
         WHERE id = ?
        """,
        (track_id, submission_id),
    )


def resolve(
    submission_id: int,
    status: str,
    reviewed_by: int,
    track_id: int | None = None,
) -> bool:
    """
    پیشکش را تأیید یا رد می‌کند.

    بازگشتی: آیا این فراخوان همان کاری بود که وضعیت را دگرگون کرد.
    اگر گردانندهٔ دیگری پیش‌تر داوری کرده باشد، False برمی‌گردد و
    کاربر دو بار آگاه نمی‌شود — تلگرام گاه یک کلیک را دوباره می‌فرستد.
    """
    with transaction() as conn:
        cursor = conn.execute(
            """
            UPDATE submissions
               SET status = ?, reviewed_by = ?, reviewed_at = datetime('now'), track_id = ?
             WHERE id = ? AND status = 'pending'
            """,
            (status, reviewed_by, track_id, submission_id),
        )
        return cursor.rowcount > 0


def pending_count() -> int:
    row = query_one("SELECT COUNT(*) AS c FROM submissions WHERE status = 'pending'")
    return int(row["c"]) if row else 0


def by_user(user_id: int, limit: int = 20) -> list[sqlite3.Row]:
    return query_all(
        "SELECT * FROM submissions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    )


def approved_count(user_id: int) -> int:
    row = query_one(
        "SELECT COUNT(*) AS c FROM submissions WHERE user_id = ? AND status = 'approved'",
        (user_id,),
    )
    return int(row["c"]) if row else 0
