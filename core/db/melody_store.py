"""
انبار نشان خطِ آهنگ.

جدا از جدول ویژگی است، چون کارشان یکی نیست: بردار ویژگی یک آرایهٔ
کوتاه و ثابت‌درازاست و برای گمانه‌زنی سبک و مداح به کار می‌آید؛
نشان خطِ آهنگ دنباله‌ای است که درازایش به درازای نوا بستگی دارد و
برای یافتنِ **اجرای دیگرِ همان نوحه**.

اندازه: نوای پنج‌دقیقه‌ای ≈ ۲٫۴ کیلوبایت. پنج هزار نوا ≈ ۱۲
مگابایت — در برابر یک گیگابایتِ اثر انگشت، هیچ.
"""

from __future__ import annotations

import logging
import sqlite3
import threading

import numpy as np

from core.db.database import execute, query_all, query_one

logger = logging.getLogger(__name__)

# ── کش گنجینه ────────────────────────────────────────────────
#
# ## چرا
#
# `corpus()` در **هر** بازجویی صدا زده می‌شود و هر بار کل جدول را
# می‌خواند و بایت‌به‌بایت به numpy برمی‌گرداند. با پنج هزار نوا
# این ده‌ها مگابایت رمزگشاییِ دوباره است، برای داده‌ای که روزها
# دست‌نخورده می‌ماند.
#
# ## چرا مُهر، و نه تنها باطل‌سازی هنگام نوشتن
#
# باطل کردن در `store` و `delete_for_track` جلوی افزودن و برداشتن
# را می‌گیرد، ولی نه جلوی خاموش شدنِ یک نوا را: `is_active = 0`
# جای دیگری نوشته می‌شود و این ماژول از آن خبر ندارد. آنگاه کش
# نوایی را نشان می‌داد که دیگر نباید دیده شود.
#
# پس پیش از هر بهره‌بری یک مُهرِ ارزان سنجیده می‌شود — دو شمارش
# نمایه‌شده — و کش تنها تا وقتی معتبر است که مُهر نجنبیده باشد.
_cache_lock = threading.Lock()
_cached_stamp: tuple | None = None
_cached_corpus: list[tuple[int, np.ndarray]] | None = None


def _stamp() -> tuple:
    """مُهرِ ارزانِ وضعیت گنجینه — با هر افزودن، برداشتن یا خاموشی می‌جنبد."""
    melody = query_one(
        "SELECT COUNT(*) AS c, COALESCE(MAX(created_at), '') AS m FROM track_melody"
    )
    active = query_one("SELECT COUNT(*) AS c FROM tracks WHERE is_active = 1")
    return (
        int(melody["c"]) if melody else 0,
        melody["m"] if melody else "",
        int(active["c"]) if active else 0,
    )


def invalidate_cache() -> None:
    """کش را باطل می‌کند."""
    global _cached_stamp, _cached_corpus
    with _cache_lock:
        _cached_stamp = None
        _cached_corpus = None


def ensure_table() -> None:
    """جدول را می‌سازد. اجرای دوباره بی‌خطر است."""
    execute(
        """
        CREATE TABLE IF NOT EXISTS track_melody (
            track_id    INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
            melody      BLOB NOT NULL,
            frames      INTEGER NOT NULL,
            version     INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def store(track_id: int, signature: np.ndarray) -> None:
    from core.audio.melody import MELODY_VERSION, to_bytes

    execute(
        """
        INSERT INTO track_melody (track_id, melody, frames, version)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(track_id) DO UPDATE SET melody = excluded.melody,
                                            frames = excluded.frames,
                                            version = excluded.version,
                                            created_at = datetime('now')
        """,
        (track_id, to_bytes(signature), int(signature.shape[1]), MELODY_VERSION),
    )
    invalidate_cache()


def get(track_id: int) -> np.ndarray | None:
    from core.audio.melody import from_bytes

    row = query_one("SELECT melody FROM track_melody WHERE track_id = ?", (track_id,))
    if row is None:
        return None
    try:
        return from_bytes(row["melody"])
    except Exception:  # noqa: BLE001
        return None


def corpus() -> list[tuple[int, np.ndarray]]:
    """
    همهٔ نشان‌های به‌روز، برای جست‌وجو.

    نشان‌های کهنه (نسخهٔ پیشین ساختار) کنار گذاشته می‌شوند — نه
    اینکه خاموش نادرست خوانده شوند.
    """
    global _cached_stamp, _cached_corpus

    from core.audio.melody import MELODY_VERSION, from_bytes

    stamp = _stamp()
    with _cache_lock:
        if _cached_corpus is not None and _cached_stamp == stamp:
            return _cached_corpus

    rows = query_all(
        """
        SELECT m.track_id, m.melody
          FROM track_melody m
          JOIN tracks t ON t.id = m.track_id
         WHERE t.is_active = 1 AND m.version >= ?
        """,
        (MELODY_VERSION,),
    )
    out: list[tuple[int, np.ndarray]] = []
    for row in rows:
        try:
            out.append((int(row["track_id"]), from_bytes(row["melody"])))
        except Exception:  # noqa: BLE001
            continue

    with _cache_lock:
        _cached_stamp = stamp
        _cached_corpus = out
    logger.debug("گنجینهٔ خطِ آهنگ از نو خوانده شد: %s نوا.", len(out))
    return out


def pending(limit: int = 50) -> list[int]:
    """نواهایی که نشان خطِ آهنگ ندارند، یا نشانشان کهنه است."""
    from core.audio.melody import MELODY_VERSION

    rows = query_all(
        """
        SELECT t.id FROM tracks t
    LEFT JOIN track_melody m ON m.track_id = t.id
         WHERE t.is_active = 1 AND t.is_indexed = 1
           AND (m.track_id IS NULL OR m.version < ?)
         ORDER BY t.created_at
         LIMIT ?
        """,
        (MELODY_VERSION, limit),
    )
    return [int(row["id"]) for row in rows]


def count() -> int:
    row = query_one("SELECT COUNT(*) AS c FROM track_melody")
    return int(row["c"]) if row else 0


def delete_for_track(track_id: int) -> None:
    execute("DELETE FROM track_melody WHERE track_id = ?", (track_id,))
    invalidate_cache()
