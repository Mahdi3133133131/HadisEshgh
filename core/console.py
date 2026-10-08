"""
درست کردن رمزگذاری پایانهٔ ویندوز.

پایانهٔ پیش‌فرض ویندوز با cp1252 کار می‌کند و هیچ نویسهٔ پارسی را
نمی‌شناسد. چون سراسر خروجی این برنامه پارسی است، بدون این اصلاح
همان نخستین چاپ با UnicodeEncodeError از پا می‌افتد.

این پیمانه باید **پیش از هر چاپ یا گزارشی** درون‌بُرد شود؛ از این رو
به هیچ چیز دیگری وابسته نیست.
"""

from __future__ import annotations

import sys


def enable_utf8_console() -> None:
    """
    خروجی و خطای استاندارد را به UTF-8 برمی‌گرداند.

    errors="replace" گذاشته شده تا اگر نویسه‌ای باز هم نمایش‌پذیر
    نبود، برنامه از کار نیفتد و تنها همان نویسه جایگزین شود؛ از دست
    رفتن یک نشانه، بهتر از فروپاشی کل ربات است.
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # برخی پوسته‌ها بازپیکربندی را برنمی‌تابند؛ نباید مانع اجرا شود.
            pass
