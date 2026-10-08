"""
پشتیبان‌گیری از پایگاه داده.

## چرا این بخش، با آنکه سند تنها اشاره‌ای به آن داشت، جدی است

گنجینهٔ اثر انگشت، **باارزش‌ترین دارایی این پروژه** است. فایل‌های
صوتی در تلگرام‌اند و از دست نمی‌روند؛ ولی اثر انگشت‌ها، نام مداحان،
سبک‌ها، دفتر توکن و کارنامهٔ کاربران تنها در همین یک پرونده‌اند.
از دست رفتنش یعنی از دست رفتن ماه‌ها کار — و بازسازی‌اش ناشدنی است.

## دو گونه پشتیبان

**سبک** — بی جدول اثر انگشت. کوچک است (چند مگابایت) و هر شب به
گروه گردانندگان فرستاده می‌شود. کاربران، توکن‌ها، نواها و کارنامه
را دارد؛ اثر انگشت‌ها را می‌توان از نو ساخت چون فایل‌ها در
تلگرام‌اند.

**کامل** — با اثر انگشت. بزرگ است و تنها با فرمان دستی ساخته
می‌شود.

## چرا از دستور BACKUP خود SQLite بهره می‌بریم

رونوشت ساده از پرونده، هنگامی که نوشتنی در جریان باشد، پشتیبانِ
شکسته می‌دهد. `sqlite3.Connection.backup` رونوشتی یکدست و بی‌عیب
می‌سازد، حتی اگر ربات در همان دم مشغول نوشتن باشد.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

from config import config
from core.db.database import get_connection

logger = logging.getLogger(__name__)

# چند پشتیبان نگه داشته شود
KEEP_BACKUPS = 14

# جدول‌هایی که در پشتیبان سبک نمی‌آیند
_HEAVY_TABLES = ("fingerprints",)


def _stamp() -> str:
    """
    مهر زمانی به گاه‌شمار خورشیدی.

    سند نام‌گذاری با تاریخ شمسی را خواسته بود. برای پرهیز از
    وابستگی تازه، تبدیل را خودمان انجام می‌دهیم.
    """
    now = datetime.now(timezone(timedelta(hours=3, minutes=30)))
    year, month, day = gregorian_to_jalali(now.year, now.month, now.day)
    return f"{year}-{month:02d}-{day:02d}"


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """
    برگردان گاه‌شمار میلادی به خورشیدی.

    الگوریتم شناخته‌شدهٔ بی‌جدول؛ برای بازهٔ سال‌های کاربردی این
    برنامه دقیق است.
    """
    g_days_in_month = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    j_days_in_month = (31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29)

    gy2 = gy - 1600
    gm2 = gm - 1
    gd2 = gd - 1

    g_day_no = 365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
    for i in range(gm2):
        g_day_no += g_days_in_month[i]
    # سال کبیسهٔ میلادی، پس از پایان اسفند
    if gm2 > 1 and ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0):
        g_day_no += 1
    g_day_no += gd2

    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053

    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461

    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365

    jm = 0
    for i in range(11):
        if j_day_no < j_days_in_month[i]:
            jm = i + 1
            break
        j_day_no -= j_days_in_month[i]
    else:
        jm = 12

    return jy, jm, j_day_no + 1


def _backup_dir() -> Path:
    path = config.base_dir / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create(light: bool = True) -> Path:
    """
    پشتیبانی می‌سازد و مسیرش را برمی‌گرداند.

    light=True یعنی بی جدول اثر انگشت.
    """
    kind = "light" if light else "full"
    destination = _backup_dir() / f"hadis_{kind}_{_stamp()}.db"

    source = get_connection()
    # isolation_level=None یعنی تراکنش خودکار باز نشود. بی این،
    # پایتون پیش از DELETE تراکنشی می‌گشاید و VACUUM — که درون
    # تراکنش شدنی نیست — با خطا می‌ایستد.
    target = sqlite3.connect(destination, isolation_level=None)
    try:
        # رونوشت یکدست، حتی اگر نوشتنی در جریان باشد
        source.backup(target)

        if light:
            for table in _HEAVY_TABLES:
                target.execute(f"DELETE FROM {table}")
            # پس از پاک کردن، پرونده را می‌فشاریم تا فضای خالی
            # بازپس گرفته شود؛ وگرنه پشتیبانِ «سبک» همان اندازهٔ
            # کامل می‌ماند.
            target.execute("VACUUM")
    finally:
        target.close()

    size_mb = destination.stat().st_size / 1024 / 1024
    logger.info("پشتیبان %s ساخته شد: %s (%.1f مگابایت)", kind, destination.name, size_mb)
    return destination


def prune(keep: int = KEEP_BACKUPS) -> int:
    """
    پشتیبان‌های کهنه را می‌زداید.

    بازگشتی: شمار زدوده‌شده‌ها.
    """
    files = sorted(
        _backup_dir().glob("hadis_*.db"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for path in files[keep:]:
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            logger.warning("زدودن «%s» شکست خورد: %s", path.name, exc)
    if removed:
        logger.info("%s پشتیبان کهنه زدوده شد.", removed)
    return removed


def summary() -> dict[str, int]:
    """چند سطر در هر جدول — برای پیام همراه پشتیبان."""
    connection = get_connection()
    counts: dict[str, int] = {}
    for table in ("users", "tracks", "fingerprints", "searches", "submissions"):
        try:
            row = connection.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
            counts[table] = int(row["c"]) if row else 0
        except sqlite3.Error:
            counts[table] = 0
    return counts


# ═════════════════════════════════════════════════════════════
#  کار زمان‌بندی‌شده
# ═════════════════════════════════════════════════════════════

async def nightly(context) -> None:
    """
    پشتیبان شبانه: می‌سازد، به گروه گردانندگان می‌فرستد، کهنه‌ها
    را می‌زداید.

    ناکامی هرگز نباید ربات را زمین بزند؛ از این رو همه چیز در
    مهار خطاست و تنها به گزارش می‌رود.
    """
    from telegram.error import TelegramError

    from core.normalize import format_size, to_persian_digits

    path: Path | None = None
    try:
        path = create(light=True)
        counts = summary()

        caption = "\n".join(
            [
                "💾 <b>پشتیبان شبانه</b>",
                "",
                f"<b>تاریخ:</b> {to_persian_digits(_stamp())}",
                f"<b>اندازه:</b> {format_size(path.stat().st_size)}",
                "",
                f"همراهان: <b>{to_persian_digits(str(counts['users']))}</b>",
                f"نواها: <b>{to_persian_digits(str(counts['tracks']))}</b>",
                f"بازجویی‌ها: <b>{to_persian_digits(str(counts['searches']))}</b>",
                "",
                "<i>این پشتیبان جدول اثر انگشت را ندارد؛ آن را می‌توان"
                " از نو ساخت، چون فایل‌ها در تلگرام‌اند.</i>",
            ]
        )

        with path.open("rb") as handle:
            await context.bot.send_document(
                chat_id=config.madahi_group_id,
                document=handle,
                filename=path.name,
                caption=caption,
                parse_mode="HTML",
            )
        logger.info("پشتیبان شبانه به گروه فرستاده شد.")

    except TelegramError as exc:
        logger.error("فرستادن پشتیبان شبانه شکست خورد: %s", exc)
    except Exception:  # noqa: BLE001
        logger.exception("پشتیبان شبانه شکست خورد.")
    finally:
        prune()
