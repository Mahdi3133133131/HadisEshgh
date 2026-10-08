"""
حافظهٔ نام‌های مستعارِ مداحان.

## چرا این هست

یک مداح در برچسبِ فایل‌ها ده جور نوشته می‌شود: فینگلیش
(`morteza yebovkzhad`)، تنها نامِ خانوادگی (`Borna`)، یا با غلط.
هر نگارش، ردیفی جدا در گنجینه می‌ساخت — و «همهٔ مداحی‌های فلانی»
هرگز کامل نبود.

## چرا خودآموز است

نگاشتِ دستی هرگز تمام نمی‌شود؛ نگارشِ تازه هر روز می‌آید. پس
به‌جای فهرستی ثابت، هر بار که گرداننده نامی را **اصلاح** کند،
همان تصحیح اینجا می‌نشیند. ربات از کارِ روزمرهٔ آدم‌ها یاد
می‌گیرد، بی آنکه کسی چیزی جدا بنویسد.

کلید، **اسکلتِ آوایی** است نه خودِ نوشته، پس یک تصحیح چند نگارشِ
نزدیک را با هم می‌گیرد.
"""

from __future__ import annotations

import logging
import sqlite3

from core.db.database import execute, query_all, query_one

logger = logging.getLogger(__name__)


def _key(text: str) -> str:
    from services.translit import skeleton

    return skeleton(text)


def remember(alias: str, canonical: str, added_by: int | None = None) -> bool:
    """
    نگارشی را به نامِ درستش گره می‌زند.

    بازگشتی: آیا چیزی نشست. `False` یعنی ارزشِ نشاندن نداشت —
    نگارش و نامِ درست یکی بودند، یا اسکلت بس کوتاه بود.
    """
    alias = (alias or "").strip()
    canonical = (canonical or "").strip()
    if not alias or not canonical:
        return False

    key = _key(alias)
    # اسکلتِ کوتاه، تصادفی می‌خواند و زیان می‌زند.
    if len(key) < 3:
        return False
    # اگر از پیش همان است، نگاشتی لازم نیست.
    if key == _key(canonical):
        return False

    try:
        execute(
            """
            INSERT INTO madah_aliases (alias_key, alias_text, canonical, added_by)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(alias_key) DO UPDATE SET
                canonical  = excluded.canonical,
                alias_text = excluded.alias_text
            """,
            (key, alias[:120], canonical[:120], added_by),
        )
    except sqlite3.Error as exc:
        logger.debug("نشاندن نامِ مستعار نشد: %s", exc)
        return False

    logger.info("نامِ مستعار آموخته شد: «%s» ← «%s»", alias, canonical)
    return True


def resolve(text: str) -> str | None:
    """
    نامِ درستِ این نگارش، اگر پیش‌تر آموخته باشیم.

    شمارندهٔ کاربرد بالا می‌رود تا بعدها بشود دید کدام نگاشت‌ها
    واقعاً به کار می‌آیند و کدام‌ها زائدند.
    """
    key = _key(text or "")
    if len(key) < 3:
        return None
    row = query_one(
        "SELECT canonical FROM madah_aliases WHERE alias_key = ?", (key,)
    )
    if row is None:
        return None
    try:
        execute(
            "UPDATE madah_aliases SET hits = hits + 1 WHERE alias_key = ?", (key,)
        )
    except sqlite3.Error:
        pass
    return str(row["canonical"])


def all_aliases() -> list[sqlite3.Row]:
    """همهٔ نگاشت‌ها، پرکاربردترین نخست."""
    return query_all(
        "SELECT * FROM madah_aliases ORDER BY hits DESC, created_at DESC"
    )


def forget(alias_text: str) -> bool:
    """نگاشتی را برمی‌دارد — وقتی نادرست از آب درآمده باشد."""
    key = _key(alias_text or "")
    if len(key) < 3:
        return False
    before = query_one(
        "SELECT COUNT(*) AS c FROM madah_aliases WHERE alias_key = ?", (key,)
    )
    execute("DELETE FROM madah_aliases WHERE alias_key = ?", (key,))
    return bool(before and int(before["c"]))


def count() -> int:
    row = query_one("SELECT COUNT(*) AS c FROM madah_aliases")
    return int(row["c"]) if row else 0
