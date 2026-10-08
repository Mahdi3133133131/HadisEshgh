"""
نمایهٔ صفحه‌های تارنماها.

## چرا جدولی جدا از گنجینه

نواهایی که در تارنماها یافت می‌شوند هنوز **نوای ما نیستند**: فایلی
در تلگرام ندارند، اثر انگشتی ندارند، و شاید هرگز کسی نخواهدشان.
نشاندنشان در جدول tracks یعنی هزاران ردیفِ بی‌فایل که هر جست‌وجوی
متنی و هر شمارشی را آلوده می‌کنند و هیچ‌کدام فرستادنی نیستند.

پس اینجا تنها **نشانی و نام** نگه داشته می‌شود. آن لحظه که کاربری
یکی را برگزید، همان یکی فرو گرفته، برچسب خورده، به تلگرام سپرده و
آنگاه به گنجینه افزوده می‌شود — با اثر انگشت، تا دفعهٔ بعد اصلاً
نیازی به تارنما نباشد.

## چرا نمایه، وقتی جست‌وجوی زنده هم داریم

دو تا از چهار تارنما اصلاً جست‌وجوی برگه‌ای ندارند: musicdel در
robots.txt خود جست‌وجو را ناروا دانسته و نتیجه‌های neynavaplus در
خودِ مرورگر ساخته می‌شوند. برای آن دو، تنها راهِ آبرومند همان
سیت‌مپی است که خودشان منتشر می‌کنند.
"""

from __future__ import annotations

import sqlite3

from core.db.database import execute, query_all, query_one
from core.normalize import normalize


def ensure_table() -> None:
    """جدول را می‌سازد. اجرای دوباره بی‌خطر است."""
    execute(
        """
        CREATE TABLE IF NOT EXISTS site_pages (
            page_url   TEXT PRIMARY KEY,
            site       TEXT NOT NULL,
            title      TEXT NOT NULL DEFAULT '',
            title_norm TEXT NOT NULL DEFAULT '',
            file_url   TEXT,
            found_at   TEXT NOT NULL DEFAULT (datetime('now')),
            seen_at    TEXT
        )
        """
    )
    execute("CREATE INDEX IF NOT EXISTS idx_pages_norm ON site_pages(title_norm)")
    execute("CREATE INDEX IF NOT EXISTS idx_pages_site ON site_pages(site)")


def remember(
    site: str,
    page_url: str,
    title: str = "",
    file_url: str | None = None,
) -> None:
    """
    صفحه‌ای را در نمایه می‌نشاند یا تازه‌اش می‌کند.

    نامِ تهی، نامِ پیشین را پاک نمی‌کند: سیت‌مپ تنها نشانی می‌دهد و
    نام، دیرتر و از خودِ صفحه به دست می‌آید. اگر تهی هم می‌نشست،
    هر گردشِ سیت‌مپ همهٔ نام‌های به‌دست‌آمده را از میان می‌برد.
    """
    execute(
        """
        INSERT INTO site_pages (page_url, site, title, title_norm, file_url)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(page_url) DO UPDATE SET
            title      = CASE WHEN excluded.title != '' THEN excluded.title
                              ELSE site_pages.title END,
            title_norm = CASE WHEN excluded.title != '' THEN excluded.title_norm
                              ELSE site_pages.title_norm END,
            file_url   = COALESCE(excluded.file_url, site_pages.file_url),
            seen_at    = datetime('now')
        """,
        (page_url, site, title, normalize(title) if title else "", file_url),
    )


def set_media(
    page_url: str, file_url: str, title: str | None = None, site: str = ""
) -> None:
    """
    نشانی فایل — و اگر تازه به دست آمده، نام — را می‌نشاند.

    **افزودن است، نه تنها به‌روزرسانی.** صفحه‌ای که از جست‌وجوی زنده
    آمده شاید هرگز در نمایه ننشسته باشد؛ اگر این UPDATE ساده بود،
    خاموش هیچ نمی‌کرد و همان رفت‌وآمد شبکه‌ای دفعهٔ بعد از نو تکرار
    می‌شد.
    """
    execute(
        """
        INSERT INTO site_pages (page_url, site, title, title_norm, file_url, seen_at)
        VALUES (?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(page_url) DO UPDATE SET
            file_url   = excluded.file_url,
            title      = CASE WHEN excluded.title != '' THEN excluded.title
                              ELSE site_pages.title END,
            title_norm = CASE WHEN excluded.title != '' THEN excluded.title_norm
                              ELSE site_pages.title_norm END,
            seen_at    = datetime('now')
        """,
        (page_url, site, title or "", normalize(title) if title else "", file_url),
    )


def get(page_url: str) -> sqlite3.Row | None:
    return query_one("SELECT * FROM site_pages WHERE page_url = ?", (page_url,))


def search(term: str, limit: int = 8) -> list[sqlite3.Row]:
    """
    جست‌وجوی نام در نمایه — واژه‌به‌واژه.

    ## چرا واژه‌به‌واژه و نه کلِ عبارت

    پیش‌تر `LIKE '%کلِ عبارت%'` بود، یعنی همهٔ واژه‌ها باید
    **پشتِ سرِ هم و به همان ترتیب** در عنوان می‌آمدند. «محمود
    کریمی شور» عملاً هیچ‌وقت نمی‌خواند، چون عنوانِ سایت‌ها
    «شور زیبا | حاج محمود کریمی» است نه آن ترتیب.

    اکنون هر واژه جدا سنجیده می‌شود و همه باید باشند (AND) —
    ترتیب مهم نیست. رتبه‌بندیِ نهایی کارِ `sites.rank` است.

    صفحه‌های بی‌نام همچنان کنار گذاشته می‌شوند: نامِ تهی با هر
    چیزی می‌خواند.
    """
    needle = normalize(term)
    if not needle:
        return []

    # واژه‌های یک‌حرفی حذف می‌شوند؛ در فارسی «و»، «به»، «از» هستند
    # و با هر عنوانی می‌خوانند.
    words = [w for w in needle.split() if len(w) > 1][:6]
    if not words:
        words = [needle]

    where = " AND ".join(["title_norm LIKE ?"] * len(words))
    params = [f"%{w}%" for w in words]
    params.append(limit)
    return query_all(
        "SELECT * FROM site_pages"
        " WHERE title_norm != '' AND " + where +
        " ORDER BY (file_url IS NULL), found_at DESC"
        " LIMIT ?",
        tuple(params),
    )


def untitled(limit: int = 30) -> list[sqlite3.Row]:
    """
    صفحه‌هایی که هنوز نامشان به دست نیامده — کارِ پرکردنِ دوره‌ای.

    ## چرا نوبتی، و نه به ترتیبِ یافته‌شدن

    پیش‌تر `ORDER BY found_at` بود، یعنی صفِ بی‌نام‌ها از جلو
    خورده می‌شد. در گنجینهٔ راستین این یعنی pelan3 با ۳۳۶ ردیفِ
    بی‌نام همهٔ سهم را می‌بُرد و musicdel و neynavaplus — که هر
    کدام ۴۰۰ ردیفِ **صددرصد** بی‌نام دارند و جست‌وجوی زنده هم
    ندارند — ده شب پشتِ صف می‌ماندند و عملاً هیچ سهمی در
    جست‌وجوی کاربر نداشتند.

    اکنون از هر سایت به نوبت برداشته می‌شود.
    """
    return query_all(
        """
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (
                       PARTITION BY site ORDER BY found_at
                   ) AS rank_in_site
              FROM site_pages
             WHERE title_norm = ''
        )
         ORDER BY rank_in_site, site
         LIMIT ?
        """,
        (limit,),
    )


def counts() -> dict[str, tuple[int, int]]:
    """برای هر تارنما: (شمار صفحه‌ها، شمار نام‌دارها)."""
    rows = query_all(
        """
        SELECT site,
               COUNT(*) AS total,
               SUM(CASE WHEN title_norm != '' THEN 1 ELSE 0 END) AS named
          FROM site_pages
         GROUP BY site
        """
    )
    return {row["site"]: (int(row["total"]), int(row["named"] or 0)) for row in rows}


def total() -> int:
    row = query_one("SELECT COUNT(*) AS c FROM site_pages")
    return int(row["c"]) if row else 0


def titled() -> int:
    """
    شمارِ صفحه‌هایی که راستی جست‌وجو‌شدنی‌اند.

    `total()` شمارِ ردیف است و گمراه‌کننده: نمایه‌ای با ۱۶۸۳ ردیف
    که ۱۱۳۶ تایش بی‌نام است، برای کاربر ۵۴۷ صفحه است نه ۱۶۸۳.
    """
    row = query_one(
        "SELECT COUNT(*) AS c FROM site_pages WHERE title_norm != ''"
    )
    return int(row["c"]) if row else 0
