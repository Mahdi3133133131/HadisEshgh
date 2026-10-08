"""
کانال‌هایی که در زمان اجرا افزوده و برداشته می‌شوند.

دو فهرست جدا، با یک ساختار:

  • **عضویت اجباری** — کاربر باید در همهٔ این‌ها عضو باشد تا بتواند
    از ربات بهره ببرد. برای تبلیغِ کانالِ دیگران به کار می‌آید.
  • **منبع** — کانال‌های مداحی که مدیرانشان ربات را افزوده‌اند؛ هر
    فایل تازه‌ای که آنجا گذاشته شود خودکار به آرشیو می‌آید.

## چرا پایگاه داده و نه .env

هر دو تا امروز در `.env` سفت شده بودند و عوض کردنشان بازراه‌اندازی
می‌خواست. کسی که با مدیر یک کانال توافق می‌کند، نباید ناچار باشد
ربات را از نو راه بیندازد.

الگو همان است که `config.is_admin` دارد: فهرست `.env` پایه است و
پایگاه داده رویش می‌افزاید.

## چرا کش

این فهرست‌ها در داغ‌ترین مسیرها خوانده می‌شوند — عضویت اجباری در هر
کاری که کاربر می‌کند. `config.is_admin` امروز بی‌کش به SQLite می‌زند
و همان اشتباه نباید تکرار شود. عمر کش کوتاه است تا افزودن یک کانال
تا چند لحظه دیگر خودش اثر کند، بی آنکه کسی چیزی را دستی تازه کند.
"""

from __future__ import annotations

import logging
import time

import sqlite3

from core.db.database import execute, query_all, query_one

logger = logging.getLogger(__name__)

REQUIRED = "required_channels"
SOURCE = "source_channels"

# فهرست تا این اندازه در حافظه می‌ماند. کوتاه است چون افزودن کانال
# باید زود اثر کند؛ ولی همین اندازه هم صدها پرس‌وجو را برمی‌دارد.
_CACHE_SECONDS = 30.0

_cache: dict[str, tuple[float, list[sqlite3.Row]]] = {}


def _table(kind: str) -> str:
    if kind not in (REQUIRED, SOURCE):
        raise ValueError(f"فهرست ناشناخته: {kind}")
    return kind


def invalidate(kind: str | None = None) -> None:
    """کش را می‌اندازد — پس از هر افزودن و برداشتن."""
    if kind is None:
        _cache.clear()
    else:
        _cache.pop(kind, None)


def active(kind: str) -> list[sqlite3.Row]:
    """کانال‌های فعالِ یک فهرست، با کش کوتاه."""
    table = _table(kind)
    now = time.monotonic()
    hit = _cache.get(table)
    if hit is not None and now - hit[0] < _CACHE_SECONDS:
        return hit[1]

    try:
        rows = query_all(
            f"SELECT * FROM {table} WHERE is_active = 1 ORDER BY added_at"
        )
    except Exception:  # noqa: BLE001
        # پایگاه دادهٔ در دسترس نبودن نباید ربات را ببندد؛ فهرست
        # تهی یعنی «تنها همان که در .env هست».
        logger.exception("خواندن فهرست %s نشد.", table)
        return []

    _cache[table] = (now, rows)
    return rows


def ids(kind: str) -> list[int]:
    return [int(row["chat_id"]) for row in active(kind)]


def get(kind: str, chat_id: int) -> sqlite3.Row | None:
    return query_one(
        f"SELECT * FROM {_table(kind)} WHERE chat_id = ?", (chat_id,)
    )


def add(
    kind: str,
    chat_id: int,
    url: str,
    title: str | None = None,
    added_by: int | None = None,
) -> bool:
    """
    کانالی می‌افزاید یا کانالِ برداشته‌شده را برمی‌گرداند.

    بازگشتی: آیا تازه بود (False یعنی از پیش در فهرست فعال بود).
    """
    table = _table(kind)
    existing = get(kind, chat_id)
    if existing is not None and existing["is_active"]:
        return False

    execute(
        f"""
        INSERT INTO {table} (chat_id, title, url, added_by, is_active)
             VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(chat_id) DO UPDATE SET
            title = excluded.title,
            url = excluded.url,
            added_by = excluded.added_by,
            is_active = 1,
            added_at = datetime('now')
        """,
        (chat_id, title, url, added_by),
    )
    invalidate(table)
    logger.info("کانال %s به فهرست %s افزوده شد.", chat_id, table)
    return True


def required_all() -> list[dict]:
    """
    همهٔ کانال‌هایی که عضویتشان اجباری است — `.env` به‌علاوهٔ
    پایگاه داده.

    کانالِ `.env` همیشه نخست می‌آید و از فهرست برداشتنی نیست:
    آن کانالِ خودِ ماست و برداشتنش با یک دستور، کارِ درستی نیست.
    برای برداشتنش باید `.env` عوض شود.
    """
    from config import config

    out: list[dict] = []
    seen: set[int] = set()

    if config.channel_id:
        out.append(
            {
                "chat_id": config.channel_id,
                "url": config.channel_url,
                "title": "کانال حدیث عشق",
                "pinned": True,
            "enforce": "always",
            }
        )
        seen.add(config.channel_id)

    for row in active(REQUIRED):
        chat_id = int(row["chat_id"])
        if chat_id in seen:
            continue
        seen.add(chat_id)
        out.append(
            {
                "chat_id": chat_id,
                "url": row["url"],
                "title": row["title"] or str(chat_id),
                "pinned": False,
                "enforce": (
                    row["enforce"] if "enforce" in row.keys() else "always"
                ),
            }
        )
    return out


def set_enforce(chat_id: int, enforce: str) -> bool:
    """
    عضویتِ این کانال را همیشگی یا یک‌باره می‌کند.

    «always» یعنی هر وقت بیرون رفت، ربات از کار می‌افتد.
    «once» یعنی تنها برای تأییدِ نخست لازم بوده و پس از آن
    اختیاری است — همان که کاربر برای کانال‌های تبلیغاتی خواست.
    """
    if enforce not in ("always", "once"):
        raise ValueError("enforce باید always یا once باشد.")
    cursor = execute(
        "UPDATE required_channels SET enforce = ? WHERE chat_id = ?",
        (enforce, int(chat_id)),
    )
    invalidate(REQUIRED)
    return cursor.rowcount > 0


def always_ids() -> list[int]:
    """کانال‌هایی که عضویتشان باید همیشه پابرجا باشد."""
    return [
        int(row["chat_id"])
        for row in required_all()
        if (row.get("enforce") or "always") == "always"
    ]


def remove(kind: str, chat_id: int) -> bool:
    """
    کانالی را از فهرست برمی‌دارد.

    ردیف پاک نمی‌شود، تنها خاموش می‌گردد: تاریخچهٔ «چه کسی کِی
    افزود» می‌ماند و افزودن دوباره‌اش هم ساده‌تر است.
    """
    table = _table(kind)
    cursor = execute(
        f"UPDATE {table} SET is_active = 0 WHERE chat_id = ? AND is_active = 1",
        (chat_id,),
    )
    invalidate(table)
    return cursor.rowcount > 0
