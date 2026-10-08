"""
بازیابی پایگاه داده از پشتیبان.

## چرا فایل را همان لحظه جایگزین نمی‌کنیم

ربات چند ریسه دارد و هر ریسه اتصال خودش را به پایگاه داده باز
نگه می‌دارد. جایگزین کردن فایل در حالی که اتصال‌ها باز است، یا
بخشی از ربات را روی فایل کهنه نگه می‌دارد، یا پروندهٔ WAL کهنه را
روی پایگاه تازه می‌نشاند و آن را خراب می‌کند.

پس کار دو گام است:

  ۱) `stage()` — فایلِ سنجیده‌شده کنار پایگاه داده (روی همان
     دیسک) با نام `restore_pending.db` گذاشته می‌شود و ربات
     خودش را می‌بندد.
  ۲) `apply_pending()` — در آغازِ اجرای بعدی، پیش از باز شدنِ هر
     اتصالی، فایل جایگزین می‌شود.

نسخهٔ پیشین هم با نام `<پایگاه>.before_restore` نگه داشته می‌شود.

## جدول اثر انگشت

پشتیبان «سبک» جدول اثر انگشت را ندارد، اما ستون `is_indexed`
نواها را «نمایه‌شده» نشان می‌دهد. بی اصلاح، موتور گمان می‌کند
همه‌چیز نمایه است و هیچ‌چیز پیدا نمی‌کند. پس اگر جدول اثر انگشت
تهی بود، نواها برای نمایه‌سازیِ دوباره نشان می‌خورند.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path

from config import config

logger = logging.getLogger(__name__)

PENDING_NAME = "restore_pending.db"
_SQLITE_MAGIC = b"SQLite format 3\x00"

# جدول‌هایی که هر پشتیبان درست باید داشته باشد
REQUIRED_TABLES = ("users", "tracks", "settings", "token_ledger")

# جدول‌هایی که در پیام تأیید شمرده می‌شوند (همان کلیدهای backup.summary)
_COUNTED = ("users", "tracks", "fingerprints", "searches", "submissions")


class RestoreError(RuntimeError):
    """فایل پشتیبان پذیرفته نشد؛ پیام برای گرداننده خوانا است."""


def incoming_path() -> Path:
    """جایی که فایلِ تازه‌فرستاده‌شده برای سنجش دانلود می‌شود."""
    return config.tmp_dir / "restore_incoming.db"


def pending_path() -> Path:
    """کنار پایگاه داده، تا جایگزینی روی همان دیسک و بی‌خطر باشد."""
    return config.database_path.with_name(PENDING_NAME)


def inspect(path: Path) -> dict[str, int]:
    """
    فایل را می‌سنجد و شمار سطرهای جدول‌های مهم را برمی‌گرداند.

    اگر فایل پایگاه دادهٔ سالمِ این ربات نباشد، RestoreError می‌دهد.
    """
    path = Path(path)
    if not path.is_file():
        raise RestoreError("فایل پیدا نشد.")

    with path.open("rb") as handle:
        if handle.read(16) != _SQLITE_MAGIC:
            raise RestoreError("این فایل پایگاه دادهٔ SQLite نیست.")

    try:
        connection = sqlite3.connect(path)
    except sqlite3.Error as exc:
        raise RestoreError(f"فایل باز نشد: {exc}") from exc

    try:
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.Error as exc:
            raise RestoreError(f"فایل خراب است: {exc}") from exc
        if not result or result[0] != "ok":
            raise RestoreError(f"بررسی یکپارچگی ناکام ماند: {result[0] if result else '?'}")

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = [name for name in REQUIRED_TABLES if name not in tables]
        if missing:
            raise RestoreError(
                "این پایگاه دادهٔ ربات حدیث عشق نیست؛ جدول‌های زیر را ندارد: "
                + "، ".join(missing)
            )

        counts: dict[str, int] = {}
        for table in _COUNTED:
            if table in tables:
                counts[table] = int(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                )
            else:
                counts[table] = 0
        return counts
    finally:
        connection.close()


def stage() -> None:
    """
    فایلِ سنجیده‌شده را برای جایگزینی در اجرای بعدی آماده می‌کند.

    پیش‌شرط: `incoming_path()` پیش‌تر دانلود شده است. پیش از
    گذاشتن، یک بار دیگر سنجیده می‌شود.
    """
    source = incoming_path()
    inspect(source)

    destination = pending_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    source.unlink(missing_ok=True)
    logger.warning("فایل بازیابی آماده شد: %s", destination)


def discard_incoming() -> None:
    incoming_path().unlink(missing_ok=True)


def _prepare_for_search(path: Path) -> int:
    """
    اگر جدول اثر انگشت تهی است، نواها را برای نمایه‌سازی دوباره
    نشان می‌زند. شمار نواهای نشان‌خورده را برمی‌گرداند.
    """
    connection = sqlite3.connect(path)
    try:
        try:
            fingerprints = connection.execute(
                "SELECT COUNT(*) FROM fingerprints"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            fingerprints = 0

        if fingerprints:
            return 0

        cursor = connection.execute(
            "UPDATE tracks SET is_indexed = 0 WHERE is_active = 1 AND is_indexed = 1"
        )
        try:
            connection.execute("UPDATE tracks SET index_attempts = 0")
        except sqlite3.OperationalError:
            pass  # ستون در پشتیبان‌های کهنه نیست؛ init_db می‌افزایدش
        connection.commit()
        return cursor.rowcount
    finally:
        connection.close()


def apply_pending() -> bool:
    """
    در آغاز اجرا، پیش از init_db: اگر فایل بازیابی منتظر است،
    جایگزین پایگاه داده می‌شود.

    ناکامی هرگز ربات را زمین نمی‌زند: فایل منتظر پاک می‌شود (تا
    چرخهٔ بی‌پایان پیش نیاید) و ربات با پایگاه داده‌ٔ کنونی بالا
    می‌آید.

    بازگشتی: آیا جایگزینی انجام شد.
    """
    pending = pending_path()
    if not pending.exists():
        return False

    target = config.database_path
    try:
        inspect(pending)
        marked = _prepare_for_search(pending)

        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            # محتوای WAL نخست به فایل اصلی بنشیند، وگرنه رونوشت ناقص است
            try:
                old = sqlite3.connect(target)
                old.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                old.close()
            except sqlite3.Error as exc:
                logger.warning("چک‌پوینت پایگاه کنونی نشد: %s", exc)
            shutil.copy2(target, target.with_name(target.name + ".before_restore"))

        # پروندهٔ WAL و SHM کهنه نباید روی پایگاه تازه بنشینند
        for suffix in ("-wal", "-shm"):
            target.with_name(target.name + suffix).unlink(missing_ok=True)

        pending.replace(target)
        logger.warning(
            "پایگاه داده از پشتیبان بازیابی شد؛ %s نوا برای نمایه‌سازی دوباره نشان خورد.",
            marked,
        )
        return True
    except Exception:  # noqa: BLE001
        logger.exception("بازیابی پایگاه داده شکست خورد؛ با پایگاه کنونی ادامه می‌دهیم.")
        pending.unlink(missing_ok=True)
        return False
