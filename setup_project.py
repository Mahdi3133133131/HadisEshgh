#!/usr/bin/env python
"""
راه‌اندازی نخستین — پوشه‌ها را می‌سازد، پیکربندی را می‌سنجد و
پایگاه داده را برپا می‌کند.

اجرا:  python setup_project.py

اجرای دوباره بی‌خطر است؛ هیچ چیزِ موجود را پاک یا بازنویسی نمی‌کند.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# باید پیش از هر چاپی انجام شود، وگرنه پایانهٔ ویندوز
# روی نخستین نویسهٔ پارسی از پا می‌افتد.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.console import enable_utf8_console  # noqa: E402

enable_utf8_console()

BASE_DIR = Path(__file__).resolve().parent

# پوشه‌هایی که در گیت نمی‌آیند و باید هنگام راه‌اندازی ساخته شوند
RUNTIME_DIRS = ("data", "logs", "tmp", "tmp/downloads", "tmp/audio")

OK = "  ✓"
ADD = "  +"
WARN = "  ⚠"
BAD = "  ✗"


def step(title: str) -> None:
    print(f"\n▸ {title}")


def ensure_directories() -> None:
    step("پوشه‌های اجرا")
    for name in RUNTIME_DIRS:
        path = BASE_DIR / name
        if path.exists():
            print(f"{OK} {name}")
        else:
            path.mkdir(parents=True, exist_ok=True)
            print(f"{ADD} {name}")


def ensure_env_file() -> bool:
    """
    اگر .env نبود، از روی .env.example می‌سازد.

    بازگشتی: آیا .env آمادهٔ استفاده است.
    """
    step("پروندهٔ پیکربندی")
    env_path = BASE_DIR / ".env"
    example_path = BASE_DIR / ".env.example"

    if env_path.exists():
        print(f"{OK} .env موجود است")
        return True

    if not example_path.exists():
        print(f"{BAD} نه .env هست نه .env.example")
        return False

    shutil.copy(example_path, env_path)
    print(f"{ADD} .env از روی .env.example ساخته شد")
    print(f"{WARN} اکنون .env را بگشایید و مقادیر واقعی را وارد کنید،")
    print("     سپس این اسکریپت را دگربار اجرا نمایید.")
    return False


def check_ffmpeg() -> None:
    """
    ffmpeg با pip نصب نمی‌شود و نبودنش، مرحلهٔ پردازش صوت را
    خاموش از کار می‌اندازد. همین‌جا هشدار داده می‌شود.
    """
    step("ابزار بیرونی")
    if shutil.which("ffmpeg"):
        print(f"{OK} ffmpeg در PATH یافت شد")
    else:
        print(f"{WARN} ffmpeg یافت نشد")
        print("     برای استخراج صوت از نماهنگ ناگزیر است.")
        print("     دریافت: https://www.gyan.dev/ffmpeg/builds/")
        print("     پس از گشودن، پوشهٔ bin را به PATH بیفزایید.")


def check_config_and_db() -> bool:
    step("پیکربندی و پایگاه داده")
    try:
        from config import config  # noqa: F401  (سنجش هنگام درون‌بُرد انجام می‌شود)
    except SystemExit:
        # config خودش پیام روشن چاپ کرده است
        return False

    print(f"{OK} پیکربندی سنجیده و پذیرفته شد")
    print(f"{OK} شمار گردانندگان: {len(config.admin_ids)}")
    print(f"{OK} شناسهٔ کانال: {config.channel_id}")

    from core.db import database

    database.init_db()
    print(f"{OK} پایگاه داده آماده شد: {config.database_path.name}")

    tables = database.query_all(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    print(f"{OK} جدول‌ها: {', '.join(row['name'] for row in tables)}")
    return True


def check_texts() -> bool:
    step("گنجینهٔ نوشتارها")
    try:
        from core import texts
    except Exception as exc:  # noqa: BLE001
        print(f"{BAD} {exc}")
        return False

    print(f"{OK} پیام‌ها: {len(texts.messages.keys())} کلید")
    print(f"{OK} دکمه‌ها: {len(texts.buttons.keys())} کلید")

    defined = sum(1 for key in texts.stickers.keys() if texts.sticker(key))
    total = len(texts.stickers.keys())
    if defined:
        print(f"{OK} برچسب‌ها: {defined} از {total} تعریف شده")
    else:
        print(f"{WARN} برچسب‌ها: هیچ‌کدام هنوز تعریف نشده‌اند")
        print("     ربات بدون آن‌ها هم کار می‌کند؛ هر وقت خواستید")
        print("     شناسه‌ها را در texts/stickers.yaml بگذارید.")
    return True


def main() -> int:
    print("═" * 62)
    print("  حدیث عشق — راه‌اندازی")
    print("═" * 62)

    ensure_directories()
    check_ffmpeg()

    if not ensure_env_file():
        print("\n" + "═" * 62)
        print("  راه‌اندازی ناتمام ماند — نخست .env را پر کنید.")
        print("═" * 62)
        return 1

    if not check_config_and_db():
        print("\n" + "═" * 62)
        print("  راه‌اندازی ناتمام ماند — پیکربندی را درست کنید.")
        print("═" * 62)
        return 1

    if not check_texts():
        return 1

    print("\n" + "═" * 62)
    print("  ✓ همه چیز آماده است.")
    print("═" * 62)
    print("\nگام بعد:  python main.py\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
