"""
انبار اثر انگشت.

جدول fingerprints با WITHOUT ROWID و کلید آغازشده به hash ساخته
شده است؛ یعنی ردیف‌های هم‌عدد کنار هم بر دیسک می‌نشینند و
بازجویی «این عدد در کدام نواهاست» یک پویش پیوسته می‌شود، نه
ده‌ها هزار پرش پراکنده.

بازجویی در دسته‌های کوچک انجام می‌شود: SQLite بر شمار پارامترهای
یک دستور سقف دارد (پیش‌فرض ۹۹۹) و اثر انگشت یک تکهٔ ده‌ثانیه‌ای
به‌آسانی از آن فراتر می‌رود.
"""

from __future__ import annotations

import logging
from typing import Iterable

import numpy as np

from core.db.database import execute, get_connection, query_one, transaction

logger = logging.getLogger(__name__)

# زیر سقف پارامترهای SQLite می‌مانیم
_CHUNK = 900

# هشی که در بیش از این شمار **نوا** آمده، ساختارِ همگانی است نه
# نشانهٔ یک نوا، و تنها نویز به بافهٔ هم‌ترازی می‌افزاید.
#
# ## چرا شمارِ نوا و نه شمارِ ردیف
#
# نخست بر پایهٔ شمارِ ردیف نوشته شد و آن غلط بود: نوای تکرارشونده
# — که مداحی اغلب هست — یک هش را در ده‌ها جای **خودش** دارد، و
# آن هش دقیقاً نشانهٔ همان نواست، نه ساختار همگانی. سقفِ ردیفی
# همان‌ها را می‌انداخت و نرخ یافتنِ کلیپ پنج‌ثانیه‌ای را از ۱۰۰٪
# به ۶۷٪ آورد.
#
# پراکندگی میان نواها سنجهٔ درست است: هشی که در دویست نوای
# متفاوت آمده، چیزی دربارهٔ هیچ‌کدام نمی‌گوید.
MAX_TRACKS_PER_HASH = 200


def store(track_id: int, hashes: np.ndarray, offsets: np.ndarray) -> int:
    """
    اثر انگشت یک نوا را می‌نشاند.

    نخست اثر انگشت پیشین همان نوا پاک می‌شود تا نمایه‌گذاری دوباره
    ردیف‌های تکراری بر جای نگذارد.

    بازگشتی: شمار ردیف‌های نشانده‌شده.
    """
    rows = [
        (int(h), track_id, int(o))
        for h, o in zip(hashes.tolist(), offsets.tolist())
    ]

    with transaction() as conn:
        conn.execute("DELETE FROM fingerprints WHERE track_id = ?", (track_id,))
        conn.executemany(
            "INSERT OR IGNORE INTO fingerprints (hash, track_id, offset_ms) VALUES (?, ?, ?)",
            rows,
        )
        conn.execute(
            "UPDATE tracks SET is_indexed = 1, updated_at = datetime('now') WHERE id = ?",
            (track_id,),
        )

    return len(rows)


def lookup_matches(
    hashes: np.ndarray, offsets: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """
    برای هر عدد بازجویی که در گنجینه هست، جفتِ (شناسهٔ نوا، فاصله)
    را برمی‌گرداند.

    «فاصله» همان زمانِ نوا منهای زمانِ بازجویی است. اگر تکه براستی
    از آن نوا بریده شده باشد، این فاصله برای همهٔ عددهای مشترک
    یکسان می‌ماند — و همین یکسانی، نشانهٔ تطبیق راستین است.
    """
    unique_hashes, inverse = np.unique(hashes, return_inverse=True)
    values = unique_hashes.tolist()

    # زمان‌های بازجویی برای هر عدد یکتا (یک عدد ممکن است چند بار بیاید)
    query_times: dict[int, list[int]] = {}
    for index, value in enumerate(inverse.tolist()):
        query_times.setdefault(value, []).append(int(offsets[index]))

    conn = get_connection()
    track_out: list[int] = []
    delta_out: list[int] = []

    for start in range(0, len(values), _CHUNK):
        chunk = values[start : start + _CHUNK]
        placeholders = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"SELECT hash, track_id, offset_ms FROM fingerprints WHERE hash IN ({placeholders})",
            chunk,
        ).fetchall()

        if not rows:
            continue

        # ── هشِ پرتکرار کنار گذاشته می‌شود ──────────────────
        #
        # عددی که در صدها نوا آمده، چیزی دربارهٔ این نوا نمی‌گوید —
        # تنها ساختاری است که همه‌جا هست (سکوت، کوبش یکنواخت). با
        # آرشیو بزرگ، همین‌ها بیشترِ ردیف‌های بازگشتی می‌شوند و هم
        # دقت را می‌خورند و هم سرعت را.
        #
        # پیش‌تر هیچ سقفی نبود و همه چیز بی‌قید برمی‌گشت.
        spread: dict[int, set[int]] = {}
        for row in rows:
            spread.setdefault(row["hash"], set()).add(row["track_id"])
        crowded = {
            value
            for value, tracks in spread.items()
            if len(tracks) > MAX_TRACKS_PER_HASH
        }
        if crowded:
            rows = [row for row in rows if row["hash"] not in crowded]

        position_of = {value: start + index for index, value in enumerate(chunk)}
        for row in rows:
            position = position_of[row["hash"]]
            for query_time in query_times.get(position, ()):
                track_out.append(row["track_id"])
                delta_out.append(row["offset_ms"] - query_time)

    if not track_out:
        empty = np.empty(0, dtype=np.int64)
        return empty, empty

    return (
        np.asarray(track_out, dtype=np.int64),
        np.asarray(delta_out, dtype=np.int64),
    )


def delete_for_track(track_id: int) -> int:
    cursor = execute("DELETE FROM fingerprints WHERE track_id = ?", (track_id,))
    return cursor.rowcount


def count_for_track(track_id: int) -> int:
    """شمار عددهای اثر انگشتِ یک نوا — برای نشان دادن پیش از برداشتن."""
    row = query_one(
        "SELECT COUNT(*) AS c FROM fingerprints WHERE track_id = ?", (track_id,)
    )
    return int(row["c"]) if row else 0


def count_rows() -> int:
    row = query_one("SELECT COUNT(*) AS c FROM fingerprints")
    return int(row["c"]) if row else 0


def count_indexed_tracks() -> int:
    row = query_one("SELECT COUNT(DISTINCT track_id) AS c FROM fingerprints")
    return int(row["c"]) if row else 0


# پس از این شمار کوششِ ناکام، نوا از صف کنار گذاشته می‌شود.
#
# سه، نه یک: ناکامیِ گذرا (شبکه لغزید، مهلت سر آمد) نباید نوایی
# را برای همیشه کنار بگذارد. ولی فایلی که ffmpeg نمی‌گشایدش، بار
# چهارم هم نمی‌گشاید — و تا امروز بی‌پایان بازآزموده می‌شد: پنج
# نوا، هر پانزده دقیقه، روزی نزدیک پانصد فرو گرفتنِ بیهوده.
#
# کنار گذاشته یعنی از این صف، نه از گنجینه: `broken_tracks` هنوز
# نشانشان می‌دهد و `clear_attempts` از نو به کارشان می‌اندازد.
MAX_INDEX_ATTEMPTS = 3


def pending_tracks(limit: int = 50) -> list[int]:
    """نواهایی که هنوز نمایه نشده‌اند و هنوز امیدی به آنها هست."""
    from core.db.database import query_all

    rows = query_all(
        """
        SELECT id FROM tracks
         WHERE is_active = 1 AND is_indexed = 0 AND file_id IS NOT NULL
           AND COALESCE(index_attempts, 0) < ?
         ORDER BY created_at
         LIMIT ?
        """,
        (MAX_INDEX_ATTEMPTS, limit),
    )
    return [int(row["id"]) for row in rows]


def broken_tracks() -> list[dict]:
    """نواهایی که چند بار کوشیدیم و نشد — تا گرداننده ببیندشان."""
    from core.db.database import query_all

    rows = query_all(
        """
        SELECT id, madah, title, duration, index_attempts
          FROM tracks
         WHERE is_active = 1 AND is_indexed = 0 AND file_id IS NOT NULL
           AND COALESCE(index_attempts, 0) >= ?
         ORDER BY id
        """,
        (MAX_INDEX_ATTEMPTS,),
    )
    return [dict(row) for row in rows]


def note_attempt(track_id: int) -> None:
    """یک کوششِ ناکام را می‌شمارد."""
    from core.db.database import execute

    execute(
        "UPDATE tracks SET index_attempts = COALESCE(index_attempts, 0) + 1"
        " WHERE id = ?",
        (track_id,),
    )


def clear_attempts(track_id: int | None = None) -> None:
    """شمارنده را صفر می‌کند — برای وقتی گرداننده از نو می‌خواهد."""
    from core.db.database import execute

    if track_id is None:
        execute("UPDATE tracks SET index_attempts = 0 WHERE is_indexed = 0")
    else:
        execute("UPDATE tracks SET index_attempts = 0 WHERE id = ?", (track_id,))
