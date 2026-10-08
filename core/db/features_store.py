"""
انبار ویژگی‌های صوتی.

جدا از جدول اثر انگشت است، چون کارشان یکی نیست: اثر انگشت
ده‌ها هزار ردیف در هر نواست و برای یافتن دقیق به کار می‌آید؛
ویژگی‌ها یک بردار کوتاه در هر نواست و برای گمانه‌زنی.

بردارها به شکل بایت خام (float32) نشانده می‌شوند، نه JSON —
هم کوچک‌ترند و هم خواندنشان به numpy بی‌درنگ است.
"""

from __future__ import annotations

import logging
import sqlite3
import threading

import numpy as np

from core.db.database import execute, query_all, query_one

logger = logging.getLogger(__name__)

# ── کش بردارها ───────────────────────────────────────────────
#
# `all_vectors()` هر بار کل جدول را می‌خواند و گمانه‌زن آن را
# بایت‌به‌بایت به numpy برمی‌گرداند. اینجا یک بار به ماتریس
# تبدیل می‌شود و تا دگرگون شدنِ گنجینه همان می‌ماند.
#
# مُهر، همان الگوی `melody_store` است و به همان دلیل: خاموش شدنِ
# یک نوا (`is_active = 0`) جای دیگری نوشته می‌شود و باطل‌سازیِ
# هنگام نوشتن، آن را نمی‌بیند.
_cache_lock = threading.Lock()
_cached_stamp: tuple | None = None
_cached_matrix: tuple[np.ndarray, np.ndarray] | None = None


def _stamp() -> tuple:
    """مُهرِ ارزانِ وضعیت انبار."""
    feats = query_one(
        "SELECT COUNT(*) AS c, COALESCE(MAX(created_at), '') AS m FROM track_features"
    )
    active = query_one("SELECT COUNT(*) AS c FROM tracks WHERE is_active = 1")
    return (
        int(feats["c"]) if feats else 0,
        feats["m"] if feats else "",
        int(active["c"]) if active else 0,
    )


def invalidate_cache() -> None:
    """کش را باطل می‌کند."""
    global _cached_stamp, _cached_matrix
    with _cache_lock:
        _cached_stamp = None
        _cached_matrix = None


def ensure_table() -> None:
    """جدول را می‌سازد. اجرای دوباره بی‌خطر است."""
    execute(
        """
        CREATE TABLE IF NOT EXISTS track_features (
            track_id    INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
            features    BLOB NOT NULL,
            tempo       REAL,
            version     INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    execute("CREATE INDEX IF NOT EXISTS idx_features_tempo ON track_features(tempo)")


def store(track_id: int, features, version: int | None = None) -> None:
    """
    ویژگی‌ها را می‌نشاند.

    نسخه از خودِ features برداشته می‌شود، نه از عددی ثابت. اگر
    ثابت می‌ماند، پس از بالا رفتن FEATURE_VERSION همهٔ بردارهای
    تازه هم «کهنه» شمرده می‌شدند و بی‌پایان از نو برداشته می‌گشتند.
    """
    from core.audio.features import FEATURE_VERSION

    if version is None:
        version = getattr(features, "version", FEATURE_VERSION)

    execute(
        """
        INSERT INTO track_features (track_id, features, tempo, version)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(track_id) DO UPDATE SET features = excluded.features,
                                            tempo = excluded.tempo,
                                            version = excluded.version,
                                            created_at = datetime('now')
        """,
        (track_id, features.to_bytes(), features.tempo, version),
    )
    invalidate_cache()


def get(track_id: int) -> sqlite3.Row | None:
    return query_one("SELECT * FROM track_features WHERE track_id = ?", (track_id,))


def has(track_id: int) -> bool:
    return get(track_id) is not None


def labelled() -> list[sqlite3.Row]:
    """
    نواهایی که هم ویژگی دارند و هم برچسب.

    تنها این‌ها به کار آموزش می‌آیند؛ نوای بی‌برچسب چیزی
    نمی‌آموزاند.
    """
    return query_all(
        """
        SELECT f.track_id, f.features, t.madah_norm, t.style
          FROM track_features f
          JOIN tracks t ON t.id = f.track_id
         WHERE t.is_active = 1
           AND (t.madah_norm IS NOT NULL AND t.madah_norm != ''
                OR t.style IS NOT NULL AND t.style != '')
        """
    )


def all_vectors() -> list[sqlite3.Row]:
    """همهٔ بردارها — برای یافتن نواهای همانند."""
    return query_all(
        """
        SELECT f.track_id, f.features
          FROM track_features f
          JOIN tracks t ON t.id = f.track_id
         WHERE t.is_active = 1
        """
    )


def voice_matrix() -> tuple[np.ndarray, np.ndarray]:
    """
    بردارهای آوا به شکل یک ماتریس، آمادهٔ سنجش برداری.

    بازگشتی: ‎(شناسهٔ نواها — آرایهٔ int64، ماتریس n×VOICE_DIM)‎

    تنها بردارهای **به‌روز** می‌آیند؛ ساختار کهنه بُعدش فرق دارد و
    در یک ماتریس نمی‌نشیند. آرایهٔ تهی، پاسخِ درست و رایج است.

    ماتریس کش می‌شود: گمانه‌زن پیش‌تر برای هر بازجویی همهٔ ردیف‌ها
    را از نو `frombuffer` می‌کرد.

    **ماتریس مشترک است — دگرگونش نکنید.**
    """
    global _cached_stamp, _cached_matrix

    from core.audio.features import VOICE_DIM, Features

    stamp = _stamp()
    with _cache_lock:
        if _cached_matrix is not None and _cached_stamp == stamp:
            return _cached_matrix

    track_ids: list[int] = []
    vectors: list[np.ndarray] = []
    for row in all_vectors():
        raw = row["features"]
        if not Features.is_current(raw):
            continue
        _style, voice = Features.from_bytes(raw)
        track_ids.append(int(row["track_id"]))
        vectors.append(voice)

    if vectors:
        result = (
            np.asarray(track_ids, dtype=np.int64),
            np.vstack(vectors).astype(np.float64),
        )
    else:
        result = (
            np.empty(0, dtype=np.int64),
            np.empty((0, VOICE_DIM), dtype=np.float64),
        )

    with _cache_lock:
        _cached_stamp = stamp
        _cached_matrix = result
    logger.debug("بردارهای آوا از نو خوانده شدند: %s نوا.", result[0].size)
    return result


def pulse_clarity_values() -> np.ndarray:
    """
    رسایی ضربانِ همهٔ نواهای به‌روز — برای میزان کردنِ آستانهٔ وزن.

    `METRICAL_THRESHOLD` از آوای ساختگی درآمده و مستنداتش خودش
    می‌گوید «با نواهای راستین شاید نیاز به جابه‌جایی داشته باشد».
    این تابع، همان دادهٔ راستین را در دسترس `/features` می‌گذارد
    تا آستانه از روی توزیع میزان شود، نه از روی گمان.

    کش نمی‌شود: تنها از فرمان گردانندگان صدا زده می‌شود.
    """
    from core.audio.features import Features

    values: list[float] = []
    for row in query_all("SELECT features FROM track_features"):
        raw = row["features"]
        if not Features.is_current(raw):
            continue
        style, _voice = Features.from_bytes(raw)
        # خانهٔ یکمِ بردار سبک، همان `pulse_clarity` است؛ ترتیبش
        # در `Features.style_vector` نشسته.
        values.append(float(style[1]))
    return np.asarray(values, dtype=np.float64)


def pending(limit: int = 50) -> list[int]:
    """
    نواهایی که ویژگی ندارند، یا ویژگی‌شان با ساختار کهنه ساخته شده.

    با بالا رفتن FEATURE_VERSION، بردارهای پیشین بُعدشان فرق می‌کند
    و دیگر خوانده نمی‌شوند. به جای دور ریختن خاموش، اینجا در صف
    برداشت دوباره می‌نشینند تا کار دوره‌ای نو کندشان.
    """
    from core.audio.features import FEATURE_VERSION

    rows = query_all(
        """
        SELECT t.id FROM tracks t
    LEFT JOIN track_features f ON f.track_id = t.id
         WHERE t.is_active = 1 AND t.is_indexed = 1
           AND (f.track_id IS NULL OR f.version < ?)
         ORDER BY t.created_at
         LIMIT ?
        """,
        (FEATURE_VERSION, limit),
    )
    return [int(row["id"]) for row in rows]


def outdated_count() -> int:
    """شمار نواهایی که ویژگی‌شان کهنه است."""
    from core.audio.features import FEATURE_VERSION

    row = query_one(
        "SELECT COUNT(*) AS c FROM track_features WHERE version < ?",
        (FEATURE_VERSION,),
    )
    return int(row["c"]) if row else 0


def current_count() -> int:
    """شمار نواهایی که ویژگی‌شان با ساختار کنونی است."""
    from core.audio.features import FEATURE_VERSION

    row = query_one(
        "SELECT COUNT(*) AS c FROM track_features WHERE version >= ?",
        (FEATURE_VERSION,),
    )
    return int(row["c"]) if row else 0


def count() -> int:
    row = query_one("SELECT COUNT(*) AS c FROM track_features")
    return int(row["c"]) if row else 0


def delete_for_track(track_id: int) -> None:
    execute("DELETE FROM track_features WHERE track_id = ?", (track_id,))
    invalidate_cache()
